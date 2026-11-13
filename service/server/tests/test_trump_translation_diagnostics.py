"""Forward-only diagnostic evidence, not translation success or dispatch policy."""
import hashlib
import json
import sys
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_trump_truth_translation import AT, approved, db, item, row


def retained(db):
    current=row(db)
    with db.get_db_connection() as c:
        found=c.execute('SELECT value_json FROM scanner_settings WHERE key=?',
                        ('trump_translation_diagnostic_v1:'+str(current['id']),)).fetchone()
    return json.loads(found['value_json']) if found else None


def test_known_editor_failure_survives_terminal_unavailable_without_private_text(db):
    import trump_truth_posts as posts,trump_truth_translation as h
    posts.ingest([item()],AT)
    calls=Mock(side_effect=ValueError('translation_review_rejected'))
    assert h.prepare(at=AT,completion=calls)['deferred']==1
    assert h.prepare(at=AT+timedelta(seconds=61),completion=calls)['prepared']==1
    diagnostic=retained(db)
    assert diagnostic is not None
    assert diagnostic['category']=='editor_rejected' and diagnostic['status']=='unavailable'
    assert diagnostic['attempt']==2 and calls.call_count==2
    with db.get_db_connection() as c:
        cache=json.loads(c.execute('SELECT value_json FROM scanner_settings WHERE key=?',(h.cache_key(row(db)),)).fetchone()['value_json'])
    assert diagnostic['cache_sha256']==hashlib.sha256(h.wire(cache).encode()).hexdigest()
    assert set(cache)=={'version','binding','attempts','status','text_he'}


def test_crash_exhaustion_records_unknown_not_an_invented_provider_cause(db):
    import trump_truth_posts as posts,trump_truth_translation as h
    posts.ingest([item()],AT)
    current=row(db);envelope=json.loads(current['message'])
    cache={'version':h.VERSION,'binding':h.binding(current,envelope),'attempts':2,'status':'working','text_he':''}
    with db.get_db_connection() as c:
        c.execute('INSERT INTO scanner_settings(key,value_json,updated_at) VALUES(?,?,?)',(h.cache_key(current),h.wire(cache),AT.isoformat()))
        c.execute('UPDATE scanner_telegram_outbox SET status=?,next_attempt_at=?',(h.WORKING,(AT-timedelta(seconds=1)).isoformat()))
    assert h.prepare(at=AT,completion=lambda *_a:pytest.fail('third inference attempt'))['prepared']==1
    assert retained(db)['category']=='unknown' and retained(db)['status']=='unavailable'


def test_working_marker_precedes_callback_and_is_not_completion_proof(db):
    import trump_truth_posts as posts,trump_truth_translation as h
    posts.ingest([item()],AT)
    def completion(*args):
        diagnostic=retained(db)
        assert diagnostic['status']=='working' and diagnostic['category']=='unknown'
        return approved(*args)
    assert h.prepare(at=AT,completion=completion)['prepared']==1
    assert retained(db)['status']=='translated' and retained(db)['category']=='none'


@pytest.mark.parametrize('failure,category',[
    (ValueError('private prompt https://private.invalid/model-output'),'unknown'),
    (ValueError('translation_not_grounded'),'not_grounded'),
    (ValueError('translation_local_unavailable'),'local_unavailable'),
])
def test_only_fixed_failure_categories_are_retained(db,failure,category):
    import trump_truth_posts as posts,trump_truth_translation as h
    posts.ingest([item()],AT)
    callback=Mock(side_effect=failure)
    h.prepare(at=AT,completion=callback);h.prepare(at=AT+timedelta(seconds=61),completion=callback)
    result=retained(db)
    assert result['category']==category
    assert not any(word in h.wire(result) for word in ('private','prompt','https','model-output'))


def test_real_schema_failure_has_typed_category_not_model_content(db):
    import trump_truth_posts as posts,trump_truth_translation as h
    posts.ingest([item()],AT)
    callback=Mock(return_value={'text_he':False})
    h.prepare(at=AT,completion=callback);h.prepare(at=AT+timedelta(seconds=61),completion=callback)
    assert retained(db)['category']=='schema_invalid'


def test_media_only_is_not_diagnosed_as_translation_failure(db):
    import trump_truth_posts as posts,trump_truth_translation as h
    posts.ingest([item('This post contains the following media: image')],AT)
    assert h.prepare(at=AT,completion=lambda *_a:pytest.fail('invented caption'))['prepared']==1
    assert retained(db)['status']=='media_only' and retained(db)['category']=='source_text_absent'


def test_old_terminal_cache_reuse_does_not_fabricate_diagnostic(db):
    import trump_truth_posts as posts,trump_truth_translation as h
    posts.ingest([item()],AT);h.prepare(at=AT,completion=approved)
    with db.get_db_connection() as c:
        c.execute('DELETE FROM scanner_settings WHERE key=?',('trump_translation_diagnostic_v1:'+str(row(db)['id']),))
        c.execute('UPDATE scanner_telegram_outbox SET status=?',(h.PENDING,))
    assert h.prepare(at=AT,completion=lambda *_a:pytest.fail('old terminal cache inference'))['prepared']==1
    assert retained(db) is None


def test_source_off_does_not_create_false_attempt_evidence(db,monkeypatch):
    import trump_truth_posts as posts,trump_truth_translation as h
    posts.ingest([item()],AT);monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_ENABLED','false')
    assert h.prepare(at=AT,completion=lambda *_a:pytest.fail('source OFF inference'))['prepared']==0
    assert retained(db) is None


def test_revoked_lease_cannot_publish_terminal_diagnostic(db):
    import trump_truth_posts as posts,trump_truth_translation as h
    posts.ingest([item()],AT)
    def completion(*args):
        with db.get_db_connection() as c:c.execute("UPDATE scanner_telegram_outbox SET status='cancelled'")
        return approved(*args)
    assert h.prepare(at=AT,completion=completion)['prepared']==0
    assert retained(db)['status']=='working' and retained(db)['category']=='unknown'


def test_diagnostic_validator_binds_cache_and_rejects_unknown_fields(db):
    import trump_truth_posts as posts,trump_truth_translation as h
    posts.ingest([item()],AT);h.prepare(at=AT,completion=approved)
    current=row(db);envelope=json.loads(current['message']);value=retained(db)
    with db.get_db_connection() as c:
        cache=json.loads(c.execute('SELECT value_json FROM scanner_settings WHERE key=?',(h.cache_key(current),)).fetchone()['value_json'])
    assert h.checked_diagnostic(current,envelope,cache,value,AT)==value
    for changed in ({**value,'cache_sha256':'0'*64},{**value,'attempt':True},
                    {**value,'category':'private arbitrary reason'},{**value,'source_text':'private'}):
        with pytest.raises(ValueError,match='translation_diagnostic_invalid'):
            h.checked_diagnostic(current,envelope,cache,changed,AT)


def test_invalid_cache_schema_becomes_fixed_diagnostic_error_without_text(db):
    import trump_truth_posts as posts,trump_truth_translation as h
    posts.ingest([item()],AT);h.prepare(at=AT,completion=approved)
    current=row(db);envelope=json.loads(current['message']);value=retained(db)
    with db.get_db_connection() as c:
        cache=json.loads(c.execute('SELECT value_json FROM scanner_settings WHERE key=?',(h.cache_key(current),)).fetchone()['value_json'])
    cache['text_he']='א'*2401
    value['cache_sha256']=hashlib.sha256(h.wire(cache).encode()).hexdigest()
    with pytest.raises(ValueError,match='^translation_diagnostic_invalid$'):
        h.checked_diagnostic(current,envelope,cache,value,AT)
