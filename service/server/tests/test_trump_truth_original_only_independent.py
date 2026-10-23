"""Independent original-relay policy tests; synthetic source/DB/ACKs only."""
import copy
import asyncio
import json
from datetime import timedelta
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest

import test_trump_truth_posts_independent as prior
import test_trump_truth_media as media_owner
import trump_truth_posts as posts

no_external_io = prior.no_external_io
media = media_owner.media
db = media_owner.db
AT = media_owner.AT
POLICY = 'original_relay_v1'
SOURCE = 'An original source statement.'
HEBREW = 'הצהרה מקורית.'


@pytest.fixture(autouse=True)
def isolated_flags(monkeypatch):
    for key in ('TELEGRAM_TRUMP_TRUTH_HEBREW_ENABLED',
                'TELEGRAM_TRUMP_TRUTH_MEDIA_ENABLED',
                'TELEGRAM_TRUMP_TRUTH_BILINGUAL_ENABLED'):
        monkeypatch.setenv(key, 'false')


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_ENABLED', 'true')
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_NOT_BEFORE', (AT-timedelta(minutes=5)).isoformat())
    monkeypatch.setenv('TELEGRAM_MARKET_NEWS_THREAD_ID', '991')


def post(body=SOURCE):
    return prior.post(body, date=AT)


@pytest.mark.parametrize('body', [
    'RT @Other: quoted text', 'RT: quoted text', 'rt: quoted text',
    'ReTruth: quoted text', 'RETRUTH: quoted text',
    'An introduction.\nRT: quoted text',
    '🦅\u200fRT: quoted text', 'R\u200bT: quoted text',
    '\u2066ReTruth\u2069: quoted text', 'Re\u200dTruth: quoted text',
    'ＲＴ： quoted text', 'ＲｅＴｒｕｔｈ： quoted text',
    'QUOTE: @Other quoted text', 'Quoted post: @Other quoted text',
    'My response. QUOTE: @Other quoted text.',
    'My response. ReTruth: @Other quoted text.',
    'https://truthsocial.com/@OtherAccount/117400000000000001',
    'https://truthsocial.com/@realDonaldTrump/117400000000000001',
    'https://truthsocial.com/users/realDonaldTrump/statuses/117400000000000001',
    'An introduction https://truthsocial.com/@OtherAccount/117400000000000001 then my comment.',
    'A'*1800+'\nRT: hidden after the retained excerpt cutoff',
    'A'*1800+'\nhttps://truthsocial.com/@realDonaldTrump/117400000000000001',
    'A'*1800+'\nR\x00T: marker hidden by a source control character',
    'A'*1800+'\nRe\x07Truth: marker hidden by a source control character',
])
def test_full_raw_reshare_or_quote_body_is_never_new_original(enabled, body):
    value, _ = posts.extract(post(body), AT)
    assert value is None, 'Original-only policy must classify before sanitizing/truncating'


@pytest.mark.parametrize('field,value', [
    ('fwd_from', NS(from_id=123)), ('forward', NS(from_id=123)),
    ('reply_to', NS(reply_to_msg_id=12)), ('reply_to_msg_id', 12),
])
def test_forward_or_reply_metadata_cannot_be_relabelled_original(enabled, field, value):
    message = post(); setattr(message, field, value)
    assert posts.extract(message, AT)[0] is None


def test_hidden_body_truth_status_entity_is_not_erased_before_classification(enabled):
    message = post('Read this quoted item before my response.')
    body_offset = len((posts.HEADER+'\n').encode('utf-16-le'))//2
    message.entities.append(NS(offset=body_offset+10, length=11,
        url='https://truthsocial.com/@OtherAccount/117400000000000001'))
    assert posts.extract(message, AT)[0] is None


@pytest.mark.parametrize('body', [SOURCE, 'A nonfinancial personal greeting.',
    '🦅😀 A direct statement.', 'The quoted price is $5; this is my comment.',
    'ART is important. START now.', 'Read https://example.invalid/article for context.',
    'This post contains the following media: image'])
def test_safe_original_retains_literal_excerpt_and_explicit_relay_limit(enabled, body):
    value, reason = posts.extract(post(body), AT)
    assert reason is None and value is not None
    assert value.get('publication_policy') == POLICY
    assert value['is_repost'] is False
    assert value['text_excerpt'] == posts.clean_excerpt(body)
    assert value['source_verification'] == 'relay_only'
    assert value['original_published_at'] is None
    assert value['truth_url'] == prior.URL


@pytest.mark.parametrize('damage', ['missing', 'wrong_version', 'repost', 'retained_marker'])
def test_active_validation_never_grandfathers_old_or_relabelled_source(enabled, damage):
    value = posts.extract(post(), AT)[0]
    assert value is not None
    if damage == 'missing': value.pop('publication_policy', None)
    if damage == 'wrong_version': value['publication_policy'] = 'original_relay_v0'
    if damage == 'repost': value['is_repost'] = True
    if damage == 'retained_marker': value['text_excerpt'] = 'RT: another person said this'
    assert not posts.valid_item(value, AT)


def seed(db, *, presentation='hebrew_v1', classified=True, status='trump_hebrew_pending'):
    """Retained old rows are constructed, not re-ingested under new policy."""
    import trump_truth_translation as h
    value = posts.extract(post(), AT)[0]
    assert value is not None
    if not classified: value.pop('publication_policy', None)
    with db.get_db_connection() as conn:
        envelope = {'item': value, 'fence': posts.fence(conn.cursor(), value)}
        if presentation: envelope['presentation'] = presentation
        message = json.dumps(envelope, ensure_ascii=False, separators=(',', ':'))
        conn.execute('INSERT INTO scanner_telegram_outbox(dedupe_key,event_type,message,status,attempts,next_attempt_at,created_at) VALUES(?,?,?,?,0,?,?)',
            (posts.PREFIX+value['truth_post_id'], posts.EVENT, message, status, AT.isoformat(), AT.isoformat()))
        row = dict(conn.execute('SELECT * FROM scanner_telegram_outbox ORDER BY id DESC LIMIT 1').fetchone())
        if presentation:
            cache = {'version': presentation, 'binding': h.binding(row,envelope), 'attempts': 1,
                     'status': 'translated', 'text_he': HEBREW}
            conn.execute('INSERT INTO scanner_settings(key,value_json,updated_at) VALUES(?,?,?)',
                (h.cache_key(row),h.wire(cache),AT.isoformat()))
    return row, envelope


@pytest.mark.parametrize('state,presentation', [
    ('trump_hebrew_pending','hebrew_v1'), ('trump_media_pending','hebrew_v1'),
    ('trump_bilingual_pending','bilingual_v1')])
def test_old_unclassified_preparation_never_requests_model(db, monkeypatch, state, presentation):
    import trump_truth_translation as h
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_BILINGUAL_ENABLED',
        'true' if presentation=='bilingual_v1' else 'false')
    row,_ = seed(db,presentation=presentation,classified=False,status=state)
    completion = Mock(side_effect=AssertionError('old unclassified source reached inference'))
    assert h.prepare(at=AT,completion=completion)['prepared'] == 0
    completion.assert_not_called()
    with db.get_db_connection() as conn:
        retained = dict(conn.execute('SELECT * FROM scanner_telegram_outbox WHERE id=?',(row['id'],)).fetchone())
    assert retained['status'] == 'cancelled' and retained['message'] == row['message']


@pytest.mark.parametrize('state,presentation', [
    ('trump_retry',None), ('trump_hebrew_ready','hebrew_v1'),
    ('trump_bilingual_ready','bilingual_v1'), ('trump_bilingual_retry','bilingual_v1')])
def test_actual_engine_does_not_send_old_unclassified_ready_or_retry(db, monkeypatch, state, presentation):
    import scanner_engine as engine
    import stock_scanner
    import trump_truth_media as media_module
    import trump_truth_bilingual as b
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_HEBREW_ENABLED','true' if presentation else 'false')
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_BILINGUAL_ENABLED','true' if presentation=='bilingual_v1' else 'false')
    monkeypatch.setattr(b,'_now',lambda:AT)
    row,_=seed(db,presentation=presentation,classified=False,status=state)
    generic = Mock(return_value='sent'); staged = Mock(return_value={'message_id':123})
    monkeypatch.setattr(stock_scanner,'send_telegram',generic)
    monkeypatch.setattr(media_module,'_send',staged)
    assert engine.process_telegram_outbox()['sent']==0
    generic.assert_not_called();staged.assert_not_called()
    with db.get_db_connection() as conn:
        assert conn.execute('SELECT message FROM scanner_telegram_outbox WHERE id=?',(row['id'],)).fetchone()['message']==row['message']
    assert engine.process_telegram_outbox()['sent']==0
    generic.assert_not_called();staged.assert_not_called()


def test_historic_unclassified_sent_record_retained_but_hidden_not_deleted(db):
    import trump_truth_public as public
    row,envelope=seed(db,classified=False,status='sent')
    with db.get_db_connection() as conn:
        conn.execute('UPDATE scanner_telegram_outbox SET sent_at=? WHERE id=?',(AT.isoformat(),row['id']))
    row['sent_at']=AT.isoformat()
    assert public.historic_envelope(row,AT)==envelope, 'Audit validator must not rewrite old history'
    with db.get_db_connection() as conn:
        before=[dict(r) for r in conn.execute('SELECT * FROM scanner_telegram_outbox')]
        cache_before=[dict(r) for r in conn.execute('SELECT * FROM scanner_settings ORDER BY key')]
        conn.execute('PRAGMA query_only=ON')
        result=public.report(conn,now=AT)
        after=[dict(r) for r in conn.execute('SELECT * FROM scanner_telegram_outbox')]
        cache_after=[dict(r) for r in conn.execute('SELECT * FROM scanner_settings ORDER BY key')]
    assert result['items']==[]
    assert before==after and cache_before==cache_after


def test_new_original_public_record_survives_source_off_without_replay(db, monkeypatch):
    import trump_truth_public as public
    row,envelope=seed(db,classified=True,status='sent')
    with db.get_db_connection() as conn:
        conn.execute('UPDATE scanner_telegram_outbox SET sent_at=? WHERE id=?',(AT.isoformat(),row['id']))
    row['sent_at']=AT.isoformat()
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_ENABLED','false')
    with db.get_db_connection() as conn:
        conn.execute('PRAGMA query_only=ON')
        result=public.report(conn,now=AT)
    assert len(result['items'])==1
    assert result['items'][0]['source_excerpt']==SOURCE
    assert result['items'][0]['text_he']==HEBREW
    assert public.historic_envelope(row,AT)==envelope


def test_old_unclassified_asset_cannot_download_even_with_consistent_descriptor(media):
    module,truth,message,_=media
    legacy=copy.deepcopy(truth.extract(message,AT)[0])
    legacy.pop('publication_policy',None)
    legacy['media']['binding']=module._binding(legacy)
    client=NS(download_media=AsyncMock())
    value=prior.run_stub(module.capture(client,message,legacy,AT))
    assert value['media']['status']!='available'
    client.download_media.assert_not_called()
    assert not module.CACHE.exists()


def test_old_unclassified_media_cache_cannot_send_or_fallback(db,media,monkeypatch):
    import trump_truth_translation as h
    module,_,_,_=media
    async def immediate(coroutine,timeout):
        assert timeout==30
        return await coroutine
    monkeypatch.setattr(asyncio,'run',prior.run_stub)
    monkeypatch.setattr(asyncio,'wait_for',immediate)
    row=media_owner.claimed(db,media,long=True)
    envelope=json.loads(row['message']);envelope['item'].pop('publication_policy',None)
    envelope['item']['media']['binding']=module._binding(envelope['item'])
    row['message']=json.dumps(envelope,ensure_ascii=False,separators=(',',':'))
    with db.get_db_connection() as conn:
        conn.execute('UPDATE scanner_telegram_outbox SET message=? WHERE id=?',(row['message'],row['id']))
        cache=json.loads(conn.execute('SELECT value_json FROM scanner_settings WHERE key=?',(h.cache_key(row),)).fetchone()['value_json'])
        cache['binding']=h.binding(row,envelope)
        conn.execute('UPDATE scanner_settings SET value_json=? WHERE key=?',(h.wire(cache),h.cache_key(row)))
    sender=Mock(return_value={'message_id':123});monkeypatch.setattr(module,'_send',sender)
    result=module.dispatch(row,{'telegram_enabled':True},AT)
    assert json.loads(result)['terminal'] is True
    sender.assert_not_called()
    assert module._receipt(row) is None


def test_actual_new_original_bilingual_pipeline_keeps_both_whole_languages_and_dedupe(db,monkeypatch):
    import scanner_engine as engine
    import trump_truth_translation as h
    import trump_truth_media as module
    import trump_truth_bilingual as b
    import trump_truth_public as public
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_BILINGUAL_ENABLED','true')
    monkeypatch.setattr(b,'_now',lambda:AT)
    value=posts.extract(post(),AT)[0]
    assert value['publication_policy']==POLICY
    assert posts.ingest([value],AT)['inserted']==1
    completion=Mock(side_effect=lambda system,payload,schema:
        {'text_he':HEBREW} if 'text_he' in schema['properties'] else
        {'faithful':True,'fluent_hebrew':True,'complete':True,'unsupported_claims':False})
    assert h.prepare(at=AT,completion=completion)['prepared']==1
    assert completion.call_count==2
    monkeypatch.setattr(h,'local_json',Mock(side_effect=AssertionError('No AI on shared send')))
    sender=Mock(return_value={'message_id':123});monkeypatch.setattr(module,'_send',sender)
    assert engine.process_telegram_outbox()=={'sent':1,'failed':0}
    assert engine.process_telegram_outbox()=={'sent':0,'failed':0}
    assert sender.call_count==1
    wire=sender.call_args.args[1]['text']
    assert SOURCE in wire and HEBREW in wire and prior.URL in wire
    assert posts.ingest([value],AT)['duplicates']==1
    with db.get_db_connection() as conn:
        conn.execute('PRAGMA query_only=ON')
        archive=public.report(conn,now=AT)
    assert len(archive['items'])==1
    assert archive['items'][0]['source_excerpt']==SOURCE
    assert archive['items'][0]['text_he']==HEBREW
    assert archive['coverage']['publication_policy']==POLICY


@pytest.mark.parametrize('state',['trump_hebrew_sending','trump_media_sending','trump_bilingual_sending'])
def test_expired_unclassified_sending_never_replays_on_restart(db,state):
    import scanner_engine as engine
    presentation='bilingual_v1' if state.startswith('trump_bilingual') else 'hebrew_v1'
    row,_=seed(db,classified=False,presentation=presentation,status=state)
    with db.get_db_connection() as conn:
        conn.execute('UPDATE scanner_telegram_outbox SET next_attempt_at=? WHERE id=?',
            ((AT-timedelta(minutes=10)).isoformat(),row['id']))
    assert engine._claim_telegram_outbox()==[]
    assert engine._claim_telegram_outbox()==[]
    with db.get_db_connection() as conn:
        retained=dict(conn.execute('SELECT * FROM scanner_telegram_outbox WHERE id=?',(row['id'],)).fetchone())
    assert retained['status']=='failed' and 'unknown_manual_review' in retained['last_error']
    assert retained['message']==row['message']


def test_filtered_shared_post_advances_cursor_then_only_new_original_is_ingested(enabled):
    import telegram_news_reader as reader
    rejected=post('RT: reshared text');rejected.id=101
    original=post();original.id=102
    client=prior.fake_client([rejected,original])
    result=prior.run_stub(reader.collect(client,prior.checkpoint(100),AT,[posts.CHANNEL]))
    assert result['status']=='ok' and result['errors']==[]
    assert len(result['items'])==1 and result['items'][0]['relay_message_id']==102
    assert result['items'][0]['publication_policy']==POLICY
    cursor=result['checkpoint']['channels'][posts.CHANNEL]
    assert cursor['last_id']==102 and cursor['rejected']=={'non_original_or_unverifiable':1}
    assert client.get_messages.call_args.kwargs=={'limit':50,'min_id':100,'reverse':True}
