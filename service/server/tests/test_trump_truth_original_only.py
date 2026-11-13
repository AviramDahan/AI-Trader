"""Original-only relay policy: synthetic source/outbox/archive, no remote IO."""
import asyncio
import copy
import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest

from test_trump_truth_posts import NOW, CHANNEL, post, enabled, db, saved
from test_trump_truth_public import conn, seed, ready

POLICY = 'original_relay_v1'


@pytest.mark.parametrize('body', [
    'RT: https://truthsocial.com/users/realDonaldTrump/statuses/117400000000000001',
    '🦅 RT @another_author Their words.',
    'ReTruth: My own earlier post.',
    '\ufeff🔁 \u200bＲＴ: My own earlier post.',
    'Thank you!\n>>QUOTE @another_author Their words.',
    'Thank you! RT: https://truthsocial.com/users/another/statuses/117400000000000001',
    'Reposted: Other content.',
    'Please read https://truthsocial.com/@another/117400000000000001',
])
def test_shared_or_quote_posts_rejected_before_ingestion(enabled, body):
    import trump_truth_posts as t
    value, reason = t.extract(post(body=body), NOW)
    assert value is None and reason == 'non_original_or_unverifiable'


@pytest.mark.parametrize('field', ['fwd_from', 'forward', 'reply_to'])
def test_telegram_forward_or_reply_does_not_claim_originality(enabled, field):
    import trump_truth_posts as t
    message = post(); setattr(message, field, NS())
    assert t.extract(message, NOW) == (None, 'non_original_or_unverifiable')


@pytest.mark.parametrize('body', [
    'An original nonfinancial statement.',
    'THE WALL STREET JOURNAL: “A headline I am discussing.”',
    'Read the article https://example.invalid/story and my view.',
    'The party will START with ART and remain SMART.',
])
def test_originals_preserve_source_and_explicit_relay_only_provenance(enabled, body):
    import trump_truth_posts as t
    value, reason = t.extract(post(body=body), NOW)
    assert reason is None and value['publication_policy'] == POLICY
    assert value['is_repost'] is False and t.valid_item(value, NOW)
    assert value['source_verification'] == 'relay_only'
    assert value['original_published_at'] is None
    assert value['text_excerpt'] == t.clean_excerpt(body)


def test_policy_rejection_advances_cursor_without_source_error(enabled):
    import trump_truth_posts as t
    import telegram_news_reader as r
    message = post(body='RT: old post'); message.id = 11
    client = NS(get_entity=AsyncMock(return_value=NS(id=t.CHANNEL_ID, username=CHANNEL, broadcast=True)),
                get_messages=AsyncMock(return_value=[message]))
    state = {'checkpoint_json': json.dumps({'channels': {CHANNEL: {
        'last_id':10, 'trump_activation':t.activation()}}})}
    result = asyncio.run(r.collect(client, state, NOW, [CHANNEL]))
    checkpoint = result['checkpoint']['channels'][CHANNEL]
    assert result['items'] == [] and result['errors'] == [] and result['status'] == 'ok'
    assert checkpoint['last_id'] == 11
    assert checkpoint['rejected'] == {'non_original_or_unverifiable':1}


def test_unclassified_old_queue_is_cancelled_without_translation_or_send(db, monkeypatch):
    import trump_truth_posts as t
    import trump_truth_translation as h
    value = t.extract(post(), NOW)[0]
    assert t.ingest([value], NOW)['inserted'] == 1
    row = saved(db)[0]; envelope = json.loads(row['message'])
    envelope['item'].pop('publication_policy', None)
    with db.get_db_connection() as c:
        c.execute('UPDATE scanner_telegram_outbox SET message=?,status=? WHERE id=?',
                  (json.dumps(envelope), h.PENDING, row['id']))
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_HEBREW_ENABLED', 'true')
    completion = Mock(side_effect=AssertionError('no inference for unclassified old row'))
    assert h.prepare(at=NOW, completion=completion)['prepared'] == 0
    completion.assert_not_called()
    assert saved(db)[0]['status'] == 'cancelled'


def test_new_original_only_guard_applies_to_retained_repost_or_missing_policy(enabled):
    import trump_truth_posts as t
    original = t.extract(post(), NOW)[0]
    for edit in ({'is_repost':True}, {'text_excerpt':'RT: retained share'},
                 {'publication_policy':'unknown'}, {'publication_policy':None}):
        changed = copy.deepcopy(original); changed.update(edit)
        assert not t.valid_item(changed, NOW)
    legacy = copy.deepcopy(original); legacy.pop('publication_policy', None)
    assert not t.valid_item(legacy, NOW)


def test_public_feed_hides_old_or_shared_rows_without_rewriting_history(conn):
    import trump_truth_public as p
    old, _ = seed(conn, 1, publication_policy=None)
    original, _ = seed(conn, 2, publication_policy=POLICY)
    shared, _ = seed(conn, 3, publication_policy=POLICY, is_repost=True)
    from test_trump_truth_public import NOW as public_now
    assert p.historic_envelope(old, public_now) is not None
    assert p.historic_envelope(shared, public_now) is not None
    before = [tuple(r) for r in conn.execute('SELECT * FROM scanner_telegram_outbox ORDER BY id')]
    ready(conn)
    data = p.report(conn, now=public_now)
    assert [x['truth_post_id'] for x in data['items']] == [json.loads(original['message'])['item']['truth_post_id']]
    assert data['coverage']['publication_policy'] == POLICY
    assert before == [tuple(r) for r in conn.execute('SELECT * FROM scanner_telegram_outbox ORDER BY id')]
