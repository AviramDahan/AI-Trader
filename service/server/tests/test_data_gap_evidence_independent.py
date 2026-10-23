"""Forward-only translation diagnostics; isolated cache/lease/privacy checks."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import types
from datetime import timedelta
from unittest.mock import Mock

import pytest

from test_trump_truth_translation import AT, approved, db, item, row
from test_trump_truth_posts_independent import no_external_io

# Exact source function extracted locally from 621d198 (not invented SQL or a
# dependency on git history in shallow CI). This is function replay, not a full
# old-image or restore test.
OLD_PRESENTATION = """def presentation(row,envelope,at=None):
    from trump_truth_bilingual import VERSION as bilingual_version,enabled as bilingual_enabled,requested
    version=envelope.get('presentation')
    if (not enabled() or version not in (VERSION,bilingual_version)
        or (version==bilingual_version and not bilingual_enabled())
        or (version==VERSION and requested())):return None
    from database import get_db_connection
    try:
        with get_db_connection() as c:
            found=c.execute('SELECT value_json FROM scanner_settings WHERE key=?',(cache_key(row),)).fetchone()
        if not found or len(found['value_json'].encode())>8192:return None
        value=checked_cache(row,envelope,json.loads(found['value_json']))
        return value if value['status'] in ('translated','unavailable','media_only','link_only') else None
    except (ValueError,TypeError,KeyError,RecursionError):return None"""


@pytest.fixture
def hmod(monkeypatch,no_external_io):
    import trump_truth_translation as current
    if os.getenv('QA_TRANSLATION_BASELINE')!='1':return current
    root=Path(__file__).resolve().parents[3]
    raw=subprocess.check_output(['git','-C',str(root),'show',
        '621d1981582b48e662f66a4ade5d93491dc39772:service/server/trump_truth_translation.py'])
    module=types.ModuleType('qa_old_translation');module.__file__=current.__file__
    exec(compile(raw,current.__file__,'exec'),module.__dict__)
    monkeypatch.setitem(sys.modules,'trump_truth_translation',module)
    return module


def setting(db,key):
    with db.get_db_connection() as c:
        value=c.execute('SELECT value_json FROM scanner_settings WHERE key=?',(key,)).fetchone()
    return json.loads(value['value_json']) if value else None


def diagnostic(db,current):return setting(db,'trump_translation_diagnostic_v1:'+str(current['id']))


def rejected_editor(system,payload,schema):
    if 'text_he' in schema['properties']:return approved(system,payload,schema)
    return dict(faithful=False,fluent_hebrew=True,complete=True,unsupported_claims=False)


def test_actual_editor_failure_diagnostic_missing_on_baseline_not_a_capacity_cause(db,hmod):
    import trump_truth_posts as t
    t.ingest([item()],AT)
    callback=Mock(side_effect=rejected_editor)
    assert hmod.prepare(at=AT,completion=callback)==dict(prepared=0,deferred=1)
    assert hmod.prepare(at=AT+timedelta(seconds=61),completion=callback)==dict(prepared=1,deferred=0)
    current=row(db);cache=setting(db,hmod.cache_key(current));value=diagnostic(db,current)
    assert cache['status']=='unavailable' and cache['attempts']==2 and callback.call_count==4
    assert value is not None and value['category']=='editor_rejected'
    assert value['status']=='unavailable' and value['attempt']==2
    assert set(cache)=={'version','binding','attempts','status','text_he'}


@pytest.fixture
def translated(db,hmod):
    import trump_truth_posts as t
    t.ingest([item()],AT);assert hmod.prepare(at=AT,completion=approved)['prepared']==1
    current=row(db);envelope=json.loads(current['message'])
    return current,envelope,setting(db,hmod.cache_key(current)),diagnostic(db,current)


@pytest.mark.parametrize('change',[
    {'version':True},{'version':'other'},{'binding':'0'*64},{'cache_sha256':'1'*64},
    {'attempt':True},{'attempt':0},{'attempt':3},{'attempt':1.0},
    {'status':'working'},{'category':'secret prompt'},{'category':'context_capacity'},
    {'recorded_at':'2026-10-22T13:00:01+00:00'}, {'recorded_at':'2026-10-22T13:00:00'},
    {'recorded_at':'not-a-time'},{'source_text':'PRIVATE_SENTINEL'},
])
def test_pure_diagnostic_rejects_foreign_shape_time_cache_or_cause(db,hmod,translated,change):
    current,envelope,cache,value=translated
    assert value is not None
    with pytest.raises(ValueError,match='translation_diagnostic_invalid'):
        hmod.checked_diagnostic(current,envelope,cache,{**value,**change},AT)


def test_diagnostic_is_cache_bound_not_mutable_authority(db,hmod,translated):
    current,envelope,cache,value=translated
    assert hmod.checked_diagnostic(current,envelope,cache,value,AT)==value
    changed=copy.deepcopy(cache);changed['attempts']=2
    with pytest.raises(ValueError,match='translation_diagnostic_invalid'):
        hmod.checked_diagnostic(current,envelope,changed,value,AT)
    with db.get_db_connection() as c:
        c.execute('UPDATE scanner_settings SET value_json=? WHERE key=?',
            ('{"SECRET_SENTINEL":"not authority"}',hmod.diagnostic_key(current)))
    # Rendering is based solely on the exact unchanged authoritative cache.
    import trump_truth_posts as t
    text=t.delivery_message(current,AT)
    assert 'לא נעלה' in text and 'SECRET_SENTINEL' not in text
    assert hmod.presentation(current,envelope,AT)==cache


def test_no_historical_backfill_no_extra_inference_no_cache_or_envelope_rewrite(db,hmod,translated):
    current,envelope,cache,value=translated
    with db.get_db_connection() as c:
        c.execute('DELETE FROM scanner_settings WHERE key=?',(hmod.diagnostic_key(current),))
        c.execute('UPDATE scanner_telegram_outbox SET status=?,next_attempt_at=?',(hmod.PENDING,AT.isoformat()))
    callback=Mock(side_effect=AssertionError('historical regeneration forbidden'))
    assert hmod.prepare(at=AT,completion=callback)['prepared']==1
    callback.assert_not_called()
    assert diagnostic(db,current) is None and row(db)['message']==current['message']
    assert setting(db,hmod.cache_key(current))==cache


def test_source_off_and_lease_revocation_never_forge_completion_evidence(db,hmod,monkeypatch):
    import trump_truth_posts as t
    t.ingest([item()],AT)
    callback=Mock(side_effect=AssertionError('OFF inference'))
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_ENABLED','false')
    assert hmod.prepare(at=AT,completion=callback)['prepared']==0
    callback.assert_not_called();assert diagnostic(db,row(db)) is None


def test_mid_request_lease_loss_does_not_persist_terminal_or_start_editor(db,hmod):
    import trump_truth_posts as t
    t.ingest([item()],AT)
    def completion(*args):
        with db.get_db_connection() as c:
            c.execute("UPDATE scanner_telegram_outbox SET status='cancelled'")
        return approved(*args)
    callback=Mock(side_effect=completion)
    assert hmod.prepare(at=AT,completion=callback)['prepared']==0
    assert callback.call_count==1
    assert diagnostic(db,row(db))['status']=='working'
    assert diagnostic(db,row(db))['category']=='unknown'


def test_crash_exhaustion_is_unknown_no_third_attempt(db,hmod):
    import trump_truth_posts as t
    t.ingest([item()],AT);current=row(db);envelope=json.loads(current['message'])
    cache=dict(version=hmod.VERSION,binding=hmod.binding(current,envelope),attempts=2,status='working',text_he='')
    with db.get_db_connection() as c:
        c.execute('INSERT INTO scanner_settings(key,value_json,updated_at) VALUES(?,?,?)',
            (hmod.cache_key(current),hmod.wire(cache),AT.isoformat()))
        c.execute('UPDATE scanner_telegram_outbox SET status=?,next_attempt_at=?',
            (hmod.WORKING,(AT-timedelta(seconds=1)).isoformat()))
    callback=Mock(side_effect=AssertionError('third attempt'))
    assert hmod.prepare(at=AT,completion=callback)['prepared']==1
    callback.assert_not_called()
    assert diagnostic(db,current)['category']=='unknown'


def test_exact_old_presentation_source_ignores_new_namespace(db,hmod,translated,monkeypatch):
    current,envelope,cache,value=translated
    assert hashlib.sha256(OLD_PRESENTATION.encode()).hexdigest()=='2889e57b0278162f4503ebec7e2bc9326ea2278b074a1b7a481c50c4352e8fc4'
    old={name:getattr(hmod,name) for name in ('enabled','VERSION','cache_key','checked_cache')}
    old['json']=json
    exec(compile(OLD_PRESENTATION,'<actual621d presentation>','exec'),old)
    assert old['presentation'](current,envelope,AT)==hmod.presentation(current,envelope,AT)==cache
    with db.get_db_connection() as c:
        assert c.execute('SELECT count(*) FROM scanner_orders').fetchone()[0]==0


@pytest.mark.parametrize('failure',[ValueError('PROMPT_SECRET https://private.invalid/'),RuntimeError('PRIVATE_SENTINEL')])
def test_arbitrary_exception_content_never_enters_diagnostic(db,hmod,failure):
    import trump_truth_posts as t
    t.ingest([item()],AT);callback=Mock(side_effect=failure)
    hmod.prepare(at=AT,completion=callback)
    hmod.prepare(at=AT+timedelta(seconds=61),completion=callback)
    value=diagnostic(db,row(db));wire=json.dumps(value)
    assert value['category']=='unknown'
    assert all(word not in wire for word in ('PROMPT_SECRET','PRIVATE_SENTINEL','https','private'))
