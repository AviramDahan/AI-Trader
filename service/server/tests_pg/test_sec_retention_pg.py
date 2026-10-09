import json

import psycopg
import pytest

import sec_history as history
import sec_retention
import sec_intelligence
from test_sec_history_pg import seed, rows, archive, confirmed, complete_seven
from test_recovery_holds import initialize_empty, record, state, target_schema


def test_unconfirmed_archive_cannot_delete(pg,tmp_path):
    seed(pg);before=rows(pg)
    repo,_key,_recipient,proof=archive(pg,tmp_path)
    with pytest.raises(ValueError,match='verified_remote_archive'):
        sec_retention.prune_archived(pg,repo,proof)
    assert rows(pg)==before


@pytest.mark.parametrize('protected',[False,True])
def test_archived_expired_history_preserves_hold_and_dependencies(pg,tmp_path,protected):
    seed(pg);initialize_empty()
    signal=record('AAPL')
    with psycopg.connect(pg) as conn:
        conn.execute("UPDATE scanner_orders SET status='recovery_uncertain' WHERE signal_id=%s",(signal['id'],))
        if protected:
            conn.execute("UPDATE scanner_signals SET scan_id='scan-old',technical_json=%s WHERE id=%s",
                         (json.dumps({'sec_snapshot_id':'old-s'}),signal['id']))
    portfolio=state();before=rows(pg)
    repo,key,_recipient,proof=archive(pg,tmp_path)
    confirmed(repo,proof)
    result=sec_retention.prune_archived(pg,repo,proof)
    assert state()==portfolio  # no cash debit/release, fill, or quantity mutation
    if protected:
        assert not any(result['deleted'].values()) and rows(pg)==before
    else:
        assert all(result['deleted'][table]==1 for table in history.TABLES if table!='si_checkpoints')
        with psycopg.connect(pg) as conn:
            assert conn.execute('SELECT last_accession FROM si_checkpoints').fetchone()[0]=='original-checkpoint'
        with target_schema(pg) as target:
            complete_seven(target)
            history.restore_archive(repo,proof['manifest_path'],key,target,workers_stopped=True)
            assert rows(target)==before  # pruned evidence remains recoverable


def test_unarchived_update_and_queued_job_are_not_deleted(pg,tmp_path):
    seed(pg);repo,_key,_recipient,proof=archive(pg,tmp_path);confirmed(repo,proof)
    with psycopg.connect(pg) as conn:
        conn.execute("UPDATE si_filing_jobs SET evidence_json='{\"changed_after_export\":true}' WHERE accession='0000320193-25-000001'")
    result=sec_retention.prune_archived(pg,repo,proof)
    assert result['deleted']['si_filing_jobs']==0
    with psycopg.connect(pg) as conn:
        assert json.loads(conn.execute("SELECT evidence_json FROM si_filing_jobs WHERE accession='0000320193-25-000001'").fetchone()[0])['changed_after_export']
        conn.execute("UPDATE si_filing_jobs SET status='queued' WHERE accession='0000320193-25-000001'")
    second=history.export_archive(pg,repo,subprocess_recipient(repo.parent/'identity'))
    # New proof is not published, so it cannot be used to delete anything.
    with pytest.raises(ValueError,match='verified_remote_archive'):
        sec_retention.prune_archived(pg,repo,second)
    confirmed(repo,second)
    result=sec_retention.prune_archived(pg,repo,second)
    assert result['deleted']['si_filing_jobs']==0
    with psycopg.connect(pg) as conn:
        assert conn.execute("SELECT status FROM si_filing_jobs WHERE accession='0000320193-25-000001'").fetchone()[0]=='queued'


def subprocess_recipient(key):
    import subprocess
    return subprocess.check_output(['age-keygen','-y',str(key)]).decode().strip()


def test_pruned_accession_cannot_reenter_discovery(pg,tmp_path):
    now=seed(pg);repo,_key,_recipient,proof=archive(pg,tmp_path);confirmed(repo,proof)
    sec_retention.prune_archived(pg,repo,proof)
    from datetime import timedelta
    accepted=now-timedelta(days=500)
    assert not sec_intelligence._queue_filing(dict(accessionNumber='0000320193-25-000001',form='4',
        acceptanceDateTime=sec_intelligence._z(accepted),primaryDocument='ownership.xml'),
        '0000320193',['AAPL'],'fresh-u',now,[10])
    with psycopg.connect(pg) as conn:
        assert not conn.execute("SELECT 1 FROM si_filing_jobs WHERE accession='0000320193-25-000001'").fetchone()
