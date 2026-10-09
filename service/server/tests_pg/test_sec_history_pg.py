"""Real age/PG with synthetic data only; no live accounts or outbound calls."""
import copy
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from psycopg import sql
import pytest

import sec_history as history
from sec_schema7_compat import assert_sec_schema7, RETENTION_INDEX_SQL
from test_recovery_holds import target_schema, initialize_empty, record, state


def complete_seven(url):
    with psycopg.connect(url) as conn:
        version = conn.execute('SELECT max(version) FROM schema_migrations').fetchone()[0]
        if version == 6:
            conn.execute((Path(__file__).parent / 'fixtures/007_sec_intelligence.sql').read_text())
            for statement in RETENTION_INDEX_SQL:
                conn.execute(statement)
            conn.execute('INSERT INTO schema_migrations(version) VALUES(7)')


def seed(url):
    complete_seven(url)
    now = datetime.now(timezone.utc)
    with psycopg.connect(url) as conn:
        for label, at in (('old', now-timedelta(days=500)), ('fresh', now-timedelta(minutes=5))):
            stamp = at.isoformat().replace('+00:00', 'Z')
            rows = {
                'si_universe_snapshots': dict(id=label+'-u', observed_at=stamp, sources_json='["synthetic"]', members_json='{}'),
                'si_filing_jobs': dict(accession='0000320193-25-'+('000001' if label=='old' else '000002'), issuer_cik='0000320193',
                    tickers_json='["AAPL"]', form='4', accepted_at=stamp, published_at=stamp, first_seen_at=stamp,
                    source_url='https://www.sec.gov/Archives/edgar/data/320193/000032019325000001/ownership.xml',
                    primary_document='ownership.xml', status='processed', attempts=0, evidence_json='{}',
                    processed_at=stamp, universe_snapshot_id=label+'-u'),
                'si_transactions': dict(event_id=label+'-tx', accession='0000320193-25-'+('000001' if label=='old' else '000002'),
                    issuer_cik='0000320193', transaction_key=label+'-key', transaction_at=stamp[:10], owners_json='[]',
                    category='purchase', body_json='{}', effective_available_at=stamp),
                'si_company_snapshots': dict(id=label+'-s', ticker='AAPL', issuer_cik='0000320193', universe_snapshot_id=label+'-u',
                    effective_available_at=stamp, created_at=stamp, expires_at=(at+timedelta(days=7)).isoformat().replace('+00:00','Z'),
                    data_confidence=.9, adjustment=.01, status='verified',
                    evidence_json=json.dumps({'facts':[{'accession':'0000320193-25-'+('000001' if label=='old' else '000002')}]}),
                    evidence_ids_json=json.dumps([label+'-tx']), policy_version='synthetic-v1'),
                'si_decisions': dict(scan_id='scan-'+label, ticker='AAPL', mode='paper', baseline_rank_score=.5,
                    sec_adjustment=.01, insider_adjustment=.01, filing_adjustment=0., enhanced_rank_score=.51,
                    sec_snapshot_id=label+'-s', evidence_ids_json=json.dumps([label+'-tx']), shortlist_limit=25, decided_at=stamp),
            }
            for table, values in rows.items():
                row = dict.fromkeys(history.REQUIRED_COLUMNS[table])
                row.update(values)
                keys = sorted(row)
                conn.execute(sql.SQL('INSERT INTO {} ({}) VALUES ({})').format(sql.Identifier(table),
                    sql.SQL(',').join(map(sql.Identifier,keys)), sql.SQL(',').join(sql.Placeholder() for _ in keys)),
                    [row[key] for key in keys])
        conn.execute("INSERT INTO si_checkpoints(issuer_cik,last_accession) VALUES('0000320193','original-checkpoint')")
    return now


def rows(url):
    with psycopg.connect(url) as conn:
        return {table: conn.execute(sql.SQL('SELECT row_to_json(t)::text FROM {} t ORDER BY {}').format(
            sql.Identifier(table),sql.SQL(',').join(map(sql.Identifier,history.KEYS[table])))).fetchall() for table in history.TABLES}


def archive(pg, tmp_path):
    key = tmp_path/'identity'
    subprocess.run(['age-keygen','-o',str(key)], check=True,capture_output=True)
    recipient = subprocess.check_output(['age-keygen','-y',str(key)]).decode().strip()
    repo = tmp_path/'repo';repo.mkdir()
    proof = history.export_archive(pg,repo,recipient)
    return repo,key,recipient,proof


def confirmed(repo,proof):
    subprocess.run(['git','init','-b','main',str(repo)],check=True,capture_output=True)
    subprocess.run(['git','add','sec'],cwd=repo,check=True,capture_output=True)
    subprocess.run(['git','-c','user.name=Synthetic','-c','user.email=synthetic@example.com','commit','-m','Encrypted fixture'],
                   cwd=repo,check=True,capture_output=True)
    remote=repo.parent/'remote.git'
    if not (remote/'HEAD').exists():
        subprocess.run(['git','init','--bare',str(remote)],check=True,capture_output=True)
        subprocess.run(['git','remote','add','origin',str(remote)],cwd=repo,check=True,capture_output=True)
    subprocess.run(['git','push','origin','HEAD:main'],cwd=repo,check=True,capture_output=True)
    commit = subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo).decode().strip()
    assert subprocess.check_output(['git','ls-remote','origin','refs/heads/main'],cwd=repo).decode().split()[0] == commit
    proof['remote_commit']=commit


def test_sec_companion_real_age_roundtrip_and_dedup(pg,tmp_path):
    seed(pg);before=rows(pg)
    repo,key,recipient,proof=archive(pg,tmp_path)
    index=json.loads((repo/'sec/index.json').read_text())
    assert 'original-checkpoint' not in (repo/'sec/index.json').read_text()
    first_hashes={part['path']:history.digest(history.location(repo,part['path']).read_bytes()) for part in proof['manifest']['chunks']}
    second=history.export_archive(pg,repo,recipient)
    assert all(history.digest(history.location(repo,path).read_bytes())==sha for path,sha in first_hashes.items())
    assert len(index['chunks'])==len(json.loads((repo/'sec/index.json').read_text())['chunks'])
    with target_schema(pg) as target:
        complete_seven(target)
        result=history.restore_archive(repo,second['manifest_path'],key,target,workers_stopped=True)
        assert result['counts']==second['manifest']['counts'] and rows(target)==before
        with psycopg.connect(target) as conn:
            assert conn.execute('SELECT count(*) FROM scanner_fills').fetchone()[0]==0
            assert conn.execute('SELECT count(*) FROM scanner_telegram_outbox').fetchone()[0]==0
        with pytest.raises(ValueError,match='destination_not_empty'):
            history.restore_archive(repo,second['manifest_path'],key,target,workers_stopped=True)
        assert rows(target)==before


def test_sec_companion_corruption_rolls_back_every_row(pg,tmp_path):
    seed(pg);repo,key,_recipient,proof=archive(pg,tmp_path)
    path=history.location(repo,proof['manifest']['chunks'][-1]['path'])
    path.write_bytes(b'damaged-synthetic-ciphertext')
    with target_schema(pg) as target:
        complete_seven(target)
        with pytest.raises(ValueError,match='cipher_checksum'):
            history.restore_archive(repo,proof['manifest_path'],key,target,workers_stopped=True)
        assert all(not value for value in rows(target).values())

def test_multichunk_companion_is_bounded_and_complete(pg,tmp_path):
    seed(pg)
    with psycopg.connect(pg) as conn:
        conn.execute('''INSERT INTO si_decisions(scan_id,ticker,mode,baseline_rank_score,sec_adjustment,
            enhanced_rank_score,evidence_ids_json,shortlist_limit,decided_at)
            SELECT 'bulk-'||n,'AAPL','shadow',.5,0,.5,'[]',25,'2026-01-01T00:00:00Z'
            FROM generate_series(1,6000) n''')
    import tracemalloc
    tracemalloc.start()
    try:
        repo,key,_recipient,proof=archive(pg,tmp_path)
        peak=tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert len([p for p in proof['manifest']['chunks'] if p['table']=='si_decisions'])>=2
    assert peak < 40 * 1024 * 1024
    with target_schema(pg) as target:
        complete_seven(target)
        restored=history.restore_archive(repo,proof['manifest_path'],key,target,workers_stopped=True)
        assert restored['counts']['si_decisions']==6002
    print('SEC_STREAMING_ARCHIVE_PASS peak_python_bytes='+str(peak))


def test_sec_companion_refuses_running_role(pg,tmp_path):
    seed(pg);repo,key,_recipient,proof=archive(pg,tmp_path)
    with target_schema(pg) as target:
        complete_seven(target)
        with psycopg.connect(target,autocommit=True) as owner:
            owner.execute('SELECT pg_advisory_lock(719322,12)')
            with pytest.raises(ValueError,match='workers_running'):
                history.restore_archive(repo,proof['manifest_path'],key,target,workers_stopped=True)
        assert all(not value for value in rows(target).values())
