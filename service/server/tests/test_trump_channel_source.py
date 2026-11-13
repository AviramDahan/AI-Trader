"""Synthetic new source and mandatory Hebrew; no Telegram or models."""
from datetime import timedelta
from types import SimpleNamespace as NS
import pytest
from test_trump_truth_posts import NOW, db, enabled, saved


def channel_post(text='The price is 100 dollars.', **kw):
    return NS(id=123,date=NOW,message=text,action=None,peer_id=NS(channel_id=1462338131),
              entities=[],fwd_from=None,reply_to=None,photo=None,document=None,**kw)


@pytest.fixture
def selected(enabled,monkeypatch):
    monkeypatch.setenv('TELEGRAM_TRUMP_SOURCE','telegram_channel_v1')
    monkeypatch.setenv('TELEGRAM_TRUMP_CHANNEL_ENABLED','true')
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_ENABLED','false')
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_HEBREW_ENABLED','true')
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_BILINGUAL_ENABLED','true')


def test_new_channel_has_real_telegram_identity_not_invented_truth_id(selected):
    import telegram_news_reader as r
    item=r.message_item(channel_post(),'real_donaldjtrump',NOW)
    assert item and item['source_kind']=='trump_telegram_channel_v1'
    assert item['truth_post_id']=='tg:1462338131:123'
    assert item['truth_url']=='https://t.me/real_DonaldJTrump/123'
    assert item['source_verification']=='channel_only'
    assert r.channel_names()==['financialjuice','real_donaldjtrump']


def test_new_source_requires_prepared_hebrew_and_never_english_fallback(db,selected):
    import telegram_news_reader as r
    import trump_truth_posts as t
    import trump_truth_translation as h
    item=r.message_item(channel_post(),'real_donaldjtrump',NOW)
    assert t.ingest([item],NOW)['inserted']==1
    row=saved(db)[0]
    assert row['status']=='trump_hebrew_pending'
    assert t.delivery_message(row,NOW) is None
    def fail(*a):raise ValueError('synthetic_failure')
    h.prepare(at=NOW,completion=fail)
    h.prepare(at=NOW+timedelta(seconds=61),completion=fail)
    row=saved(db)[0]
    assert row['status']=='cancelled'
    assert t.delivery_message(row,NOW+timedelta(seconds=62)) is None


def test_new_source_success_dedupe_restart_keeps_only_hebrew(db,selected):
    import telegram_news_reader as r
    import trump_truth_posts as t
    import trump_truth_translation as h
    item=r.message_item(channel_post(),'real_donaldjtrump',NOW)
    assert t.ingest([item],NOW)['inserted']==1
    assert t.ingest([item],NOW)['duplicates']==1
    def ok(system,payload,schema):
        return {'text_he':'המחיר הוא 100 דולר.'} if 'text_he' in schema['properties'] else dict(faithful=True,fluent_hebrew=True,complete=True,unsupported_claims=False)
    assert h.prepare(at=NOW,completion=ok)['prepared']==1
    text=t.delivery_message(saved(db)[0],NOW)
    assert 'המחיר הוא 100 דולר.' in text and 'The price' not in text
    assert 'Truth Social' not in text and item['truth_url'] not in text
    assert 'מקור:' not in text and 'שיוך לחשבון רשמי לא אומת' in text


def test_new_source_long_media_caption_omits_source_link(selected):
    import trump_truth_media as media
    item={'source_kind':'trump_telegram_channel_v1',
          'truth_url':'https://t.me/real_DonaldJTrump/123'}
    planned=media.delivery_plan('דיווח בעברית '*120,item)
    assert planned['text'] is not None
    assert item['truth_url'] not in planned['caption']
    assert 'מקור:' not in planned['caption']
    assert 'שיוך לחשבון רשמי לא אומת' in planned['caption']
