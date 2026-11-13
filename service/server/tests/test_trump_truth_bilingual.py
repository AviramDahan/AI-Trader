"""Complete literal two-language Trump notices; no external I/O or inference."""
import asyncio
import json
import re
from datetime import timedelta
from unittest.mock import Mock

import pytest

import test_trump_truth_media as old
import test_trump_truth_posts_independent as source_controls
import trump_truth_bilingual as b

media=old.media
db=old.db
AT=old.AT
no_external_io=source_controls.no_external_io


@pytest.fixture(autouse=True)
def bilingual(monkeypatch,no_external_io):
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_BILINGUAL_ENABLED','true')
    monkeypatch.setattr(b,'_now',lambda:AT)
    async def immediate(coroutine,timeout):return await coroutine
    monkeypatch.setattr(asyncio,'wait_for',immediate)
    monkeypatch.setattr(asyncio,'run',source_controls.run_stub)


def visible(text):return re.sub('[\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]','',text)


def item(media,body='An original source policy statement.',asset=False):
    m,t,msg,_=media
    text=t.HEADER+'\n'+body+'\n'+t.LABEL;msg.message=text
    msg.entities[0].offset=len(text[:text.rindex(t.LABEL)].encode('utf-16-le'))//2
    if asset:return old.captured(media)[0]
    msg.media=None;msg.photo=None;msg.document=None
    return t.extract(msg,AT)[0]


def claimed(db,media,*,source='An original source policy statement.',hebrew='אמירה מקורית על מדיניות.',asset=False):
    _,t,_,_=media;value=item(media,source,asset)
    assert t.ingest([value],AT)['inserted']==1
    import trump_truth_translation as h
    call=Mock(side_effect=lambda system,payload,schema:{'text_he':hebrew} if 'text_he' in schema['properties'] else
        {'faithful':True,'fluent_hebrew':True,'complete':True,'unsupported_claims':False})
    assert h.prepare(at=AT,completion=call)['prepared']==1
    with db.get_db_connection() as c:
        row=dict(c.execute('SELECT * FROM scanner_telegram_outbox ORDER BY id DESC LIMIT 1').fetchone())
        assert row['status']==b.READY
        lease=(AT+timedelta(minutes=5)).isoformat()
        c.execute('UPDATE scanner_telegram_outbox SET status=?,next_attempt_at=? WHERE id=?',(b.SENDING,lease,row['id']))
    row.update(status=b.SENDING,next_attempt_at=lease)
    return row


def test_whole_combined_hebrew_first_and_actual_source_visible(media):
    value=item(media)
    parts=b.plan(value,{'status':'translated','text_he':'אמירה מקורית על מדיניות.'})
    assert len(parts)==1 and parts[0]['stage']=='combined'
    text=visible(parts[0]['text'])
    assert text.index('אמירה מקורית')<text.index(value['text_excerpt'])
    assert 'original relay excerpt' in text.lower() and 'NOT VERIFIED' in text
    assert '…' not in text


@pytest.mark.parametrize('status,body',[('unavailable','An original source policy statement.'),
    ('media_only','This post contains the following media: image'),('link_only','RT https://example.invalid/')])
def test_unavailable_media_and_link_statuses_are_truthful_in_both_languages(media,status,body):
    # Pure historical plan must remain readable for retained old receipts;
    # new extraction never grants publication authority to a link-only repost.
    value=item(media,body) if status!='link_only' else item(media)
    if status=='link_only':
        value.update(text_excerpt='RT [קישור בגוף הפוסט — לצפייה במקור]',is_repost=True)
        value.pop('publication_policy',None)
    if status=='media_only':value['has_media']=True
    parts=b.plan(value,{'status':status,'text_he':''})
    text=visible('\n'.join(p['text'] for p in parts))
    assert re.search('[\u0590-\u05ff]',text) and ('Original relay excerpt' in text or 'No source text' in text or 'Link-only repost' in text)
    assert 'This post contains' not in text and 'example.invalid' not in text
    if status=='unavailable':assert value['text_excerpt'] in text


def test_long_approved_hebrew_and_source_are_never_clipped(media):
    source=('1 '*800).strip();hebrew=('א1 '*800).strip()
    value=item(media,source)
    parts=b.plan(value,{'status':'translated','text_he':hebrew})
    from telegram_presentation import utf16_length
    assert [p['stage'] for p in parts]==['hebrew','english']
    assert all(utf16_length(p['text'])<=4096 for p in parts)
    assert hebrew in visible(parts[0]['text']) and source in visible(parts[1]['text'])
    assert all('…' not in p['text'] for p in parts)


def test_real_asset_plus_long_bilingual_has_three_bounded_parts(db,media,monkeypatch):
    row=claimed(db,media,source=('1 '*800).strip(),hebrew=('א1 '*800).strip(),asset=True)
    sender=Mock(side_effect=[{'message_id':121},{'message_id':122},{'message_id':123}])
    import trump_truth_media as m
    monkeypatch.setattr(m,'_send',sender)
    assert b.dispatch(row,{'telegram_enabled':True},AT)=='sent'
    assert [c.args[0] for c in sender.call_args_list]==['sendPhoto','sendMessage','sendMessage']
    saved=b.receipt(row)
    assert saved['status']=='complete' and set(saved['acks'])=={'media','hebrew','english'}
    assert b.dispatch(row,{'telegram_enabled':True},AT)=='sent' and sender.call_count==3


def test_retry_after_known_hebrew_ack_never_repeats_it(db,media,monkeypatch):
    row=claimed(db,media,source=('1 '*800).strip(),hebrew=('א1 '*800).strip())
    import trump_truth_media as m
    sender=Mock(side_effect=[{'message_id':121},{'retry':True,'reason':'rate_limited'},{'message_id':122}])
    monkeypatch.setattr(m,'_send',sender)
    assert json.loads(b.dispatch(row,{'telegram_enabled':True},AT))['terminal'] is False
    assert b.receipt(row)['acks']=={'hebrew':121}
    assert b.dispatch(row,{'telegram_enabled':True},AT)=='sent'
    assert sender.call_count==3


@pytest.mark.parametrize('damage',['unknown','revoked','cache_lost','lease_expired'])
def test_no_next_part_after_unknown_or_lost_authority(db,media,monkeypatch,damage):
    row=claimed(db,media,source=('1 '*800).strip(),hebrew=('א1 '*800).strip())
    import trump_truth_media as m
    import trump_truth_translation as h
    def send(*args):
        if damage=='revoked':monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_BILINGUAL_ENABLED','false')
        if damage=='cache_lost':
            with db.get_db_connection() as c:c.execute('DELETE FROM scanner_settings WHERE key=?',(h.cache_key(row),))
        if damage=='lease_expired':monkeypatch.setattr(b,'_now',lambda:AT+timedelta(minutes=6))
        return {'unknown':True} if damage=='unknown' else {'message_id':121}
    sender=Mock(side_effect=send);monkeypatch.setattr(m,'_send',sender)
    result=b.dispatch(row,{'telegram_enabled':True},None if damage=='lease_expired' else AT)
    assert json.loads(result)['terminal'] is True and sender.call_count==1


def test_old_media_complete_cannot_certify_bilingual_english(db,media,monkeypatch):
    row=claimed(db,media)
    import trump_truth_media as m
    with db.get_db_connection() as c:
        c.execute('INSERT INTO scanner_settings(key,value_json,updated_at) VALUES(?,?,?)',(m.receipt_key(row),'{}',AT.isoformat()))
    sender=Mock(return_value={'message_id':121});monkeypatch.setattr(m,'_send',sender)
    assert b.dispatch(row,{'telegram_enabled':True},AT)=='sent'
    assert sender.call_count==1 and b.receipt(row)['version']==b.RECEIPT_VERSION


def test_serialized_ack_key_order_is_not_plan_order_but_prefix_is_strict(db,media,monkeypatch):
    row=claimed(db,media,source=('1 '*800).strip(),hebrew=('א1 '*800).strip(),asset=True)
    import trump_truth_media as m
    sender=Mock(side_effect=[{'message_id':121},{'message_id':122},{'retry':True,'reason':'rate_limited'},{'message_id':123}])
    monkeypatch.setattr(m,'_send',sender)
    assert json.loads(b.dispatch(row,{'telegram_enabled':True},AT))['terminal'] is False
    retained=b.receipt(row)
    assert set(retained['acks'])=={'media','hebrew'}
    assert b.dispatch(row,{'telegram_enabled':True},AT)=='sent'
    assert sender.call_count==4
    damaged=b.receipt(row);damaged.update(status='retry',active_stage='media')
    with pytest.raises(ValueError):b._checked(row,damaged)


def test_requested_without_hebrew_never_falls_back_to_english(db,media,monkeypatch):
    _,t,_,_=media;value=item(media)
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_HEBREW_ENABLED','false')
    assert t.ingest([value],AT)['inserted']==0
    with db.get_db_connection() as c:assert c.execute('SELECT COUNT(*) n FROM scanner_telegram_outbox').fetchone()['n']==0


def test_old_selectors_ignore_new_bilingual_queue(db,media):
    row=claimed(db,media)
    with db.get_db_connection() as c:
        assert not c.execute("SELECT id FROM scanner_telegram_outbox WHERE status IN ('trump_hebrew_ready','trump_hebrew_retry','trump_media_ready','trump_media_retry','trump_pending','trump_retry')").fetchall()


def test_publication_requires_all_acks_and_rejects_substituted_cached_translation(db,media,monkeypatch):
    row=claimed(db,media,source=('1 '*800).strip(),hebrew=('א1 '*800).strip())
    import trump_truth_media as m
    import trump_truth_translation as h
    sender=Mock(side_effect=[{'message_id':121},{'message_id':122}]);monkeypatch.setattr(m,'_send',sender)
    assert b.dispatch(row,{'telegram_enabled':True},AT)=='sent'
    envelope=json.loads(row['message'])
    with db.get_db_connection() as c:
        c.execute('UPDATE scanner_telegram_outbox SET status=?,sent_at=? WHERE id=?',('sent',AT.isoformat(),row['id']))
    row.update(status='sent',sent_at=AT.isoformat())
    with db.get_db_connection() as c:
        assert b.published_receipt(row,envelope,c,AT) is True
        complete=b.receipt(row,c)
        invalid={**complete,'acks':{'hebrew':121}}
        c.execute('UPDATE scanner_settings SET value_json=? WHERE key=?',(m.wire(invalid),b.receipt_key(row)))
        assert b.published_receipt(row,envelope,c,AT) is False
        c.execute('UPDATE scanner_settings SET value_json=? WHERE key=?',(m.wire(complete),b.receipt_key(row)))
        cache=json.loads(c.execute('SELECT value_json FROM scanner_settings WHERE key=?',(h.cache_key(row),)).fetchone()['value_json'])
        cache['text_he']=('ב1 '*800).strip()
        assert h.checked_cache(row,envelope,cache)
        c.execute('UPDATE scanner_settings SET value_json=? WHERE key=?',(m.wire(cache),h.cache_key(row)))
        assert b.published_receipt(row,envelope,c,AT) is False
        c.execute('DELETE FROM scanner_settings WHERE key=?',(h.cache_key(row),))
        assert b.published_receipt(row,envelope,c,AT) is True  # UI must say NOT_RETAINED; no invented Hebrew.
    assert sender.call_count==2
