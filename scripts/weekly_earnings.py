"""Weekly official Earnings Whispers image; local secrets, durable send guard.

Default is a read-only preview. --send is used by the weekly scheduled task.
Permission to redistribute the chart was confirmed by the owner on 2026-09-25.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import os
from datetime import datetime, timedelta, date
from io import BytesIO
import json
from pathlib import Path
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from dotenv import dotenv_values
from PIL import Image
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'service' / 'server'))
from telegram_presentation import telegram_text
FEED = 'https://www.reddit.com/r/EarningsWhisper/new/.rss'
STATE = ROOT / '.runtime' / 'weekly_earnings.sqlite'
HEADERS = {'User-Agent': 'AI-Trader earnings calendar/1.0'}
NS = {'a': 'http://www.w3.org/2005/Atom'}


def next_monday(today: date) -> date:
    return today + timedelta(days=7-today.weekday())


def delivery_window(now: datetime) -> bool:
    """Friday evening, with bounded weekend catch-up for delayed runners.

    All eligible dates address the same next-Monday week. Monday is rejected
    before network access, preventing an old delayed job from selecting a
    different week. Durable weekly claims remain the authority for retries.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Delivery time requires a timezone')
    local=now.astimezone(ZoneInfo('Asia/Jerusalem'))
    return (local.weekday()==4 and local.hour>=18) or local.weekday() in (5,6)


def find_calendar(xml: bytes, week: date) -> dict:
    for entry in ET.fromstring(xml).findall('a:entry', NS):
        title = entry.findtext('a:title', default='', namespaces=NS)
        if entry.findtext('a:author/a:name', default='', namespaces=NS).lower() != '/u/epswhispers':
            continue
        match = re.fullmatch(r'The Most Anticipated Earnings Releases for the Week of (\w+ \d{1,2}, \d{4})', title)
        if not match:
            continue
        try:
            stated = datetime.strptime(match[1], '%B %d, %Y').date()
        except ValueError:
            continue
        if stated != week:
            continue
        body = BeautifulSoup(entry.findtext('a:content', default='', namespaces=NS), 'html.parser')
        images = [a['href'] for a in body.find_all('a', href=True)
                  if re.fullmatch(r'https://i\.redd\.it/[a-zA-Z0-9]+\.(?:png|jpg|jpeg)', a['href'])]
        links = [a['href'] for a in body.find_all('a', href=True)
                 if a['href'].startswith('https://www.reddit.com/r/EarningsWhisper/comments/')]
        tickers = list(dict.fromkeys(re.findall(r'#([A-Z][A-Z0-9.\-]{0,9})\b', body.get_text(' ',strip=True))))
        if images and links and tickers:
            return {'week': week.isoformat(), 'title': title, 'image_url': images[0],
                    'source_url': links[0], 'tickers': tickers}
    raise ValueError('Current next-week official calendar not published or feed format changed')


def fetch_calendar(week: date, session) -> dict:
    response = session.get(FEED, headers=HEADERS, timeout=30)
    if response.status_code != 200:
        raise ValueError(f'Calendar feed unavailable: HTTP {response.status_code}; retry later')
    if len(response.content) > 2_000_000:
        raise ValueError('Calendar feed exceeds size limit')
    return find_calendar(response.content, week)


def photo_bytes(url: str, session) -> bytes:
    if not re.fullmatch(r'https://i\.redd\.it/[a-zA-Z0-9]+\.(?:png|jpg|jpeg)',url):
        raise ValueError('Unapproved image host/path')
    response = session.get(url, headers=HEADERS, timeout=30, allow_redirects=False, stream=True)
    if response.status_code != 200:
        raise ValueError(f'Calendar image unavailable: HTTP {response.status_code}')
    data = bytearray()
    for chunk in response.iter_content(65536):
        data.extend(chunk)
        if len(data) > 9_000_000:
            raise ValueError('Calendar image exceeds Telegram-safe size limit')
    with Image.open(BytesIO(data)) as im:
        if im.format not in ('PNG','JPEG') or min(im.size)<500 or sum(im.size)>10000:
            raise ValueError('Invalid calendar image dimensions/format')
        im.verify()
    return bytes(data)


def caption(item: dict, community: str='') -> str:
    start = date.fromisoformat(item['week']); end = start+timedelta(days=4)
    text = (f"דוחות לשבוע {start:%d.%m.%Y}–{end:%d.%m.%Y}\n\n"
            "מבחר מדווחות: " + ' · '.join(item['tickers'][:30]) +
            "\nמועדים עשויים להשתנות.\n"
            "Before Open / After Close — לפני הפתיחה / אחרי הסגירה בארה״ב.")
    if community.startswith('https://t.me/') and len(community)<150:
        text += '\n\nלהצטרפות לקהילה:\n'+community
    if len(text.encode('utf-16-le'))//2 > 1024:
        raise ValueError('Caption exceeds Telegram limit')
    return text


def destination_binding(bot_id, chat_id, topic):
    """Public receipt binding; raw bot/chat/thread identities stay private."""
    return hashlib.sha256(json.dumps(['weekly-earnings-v2',int(bot_id),int(chat_id),int(topic)],
                                    separators=(',',':'),ensure_ascii=True).encode()).hexdigest()


def validate_record(record, week):
    if (not isinstance(record,dict) or record.get('week')!=week
            or record.get('status') not in ('sent','sending','retryable','pin_pending','pinned')):
        raise ValueError('Invalid cloud delivery state')
    allowed={'week','status','schema_version','message_id','destination_binding','previous_pin'}
    if set(record)-allowed:raise ValueError('Invalid cloud receipt fields')
    if record['status'] in ('pin_pending','pinned'):
        if (record.get('schema_version')!=2 or type(record.get('message_id')) is not int
                or record['message_id']<=0 or not re.fullmatch('[0-9a-f]{64}',record.get('destination_binding',''))):
            raise ValueError('Invalid known-message receipt')
    previous=record.get('previous_pin')
    if previous is not None:
        if (record.get('status') not in ('pin_pending','pinned')
                or not isinstance(previous,dict) or set(previous)!={'week','message_id','destination_binding'}
                or type(previous.get('message_id')) is not int or previous['message_id']<=0
                or not re.fullmatch('[0-9a-f]{64}',previous.get('destination_binding',''))
                or previous.get('week')!=(date.fromisoformat(week)-timedelta(days=7)).isoformat()):
            raise ValueError('Invalid previous weekly pin receipt')
        if previous['destination_binding']!=record['destination_binding'] or previous['message_id']==record['message_id']:
            raise ValueError('Invalid previous weekly pin binding')
    return record


def _bot_id(token,session):
    try:
        r=session.get(f'https://api.telegram.org/bot{token}/getMe',timeout=15)
        body=r.json();bot=body.get('result')
        if (r.status_code!=200 or body.get('ok') is not True or not isinstance(bot,dict)
                or bot.get('is_bot') is not True or type(bot.get('id')) is not int or bot['id']<=0):
            raise ValueError()
        return bot['id']
    except Exception:
        raise ValueError('Telegram bot identity not verified') from None


def _pin_request(session,token,method,chat,mid,*,silent=False):
    data={'chat_id':chat,'message_id':mid}
    if silent:data['disable_notification']=True
    try:
        response=session.post(f'https://api.telegram.org/bot{token}/{method}',data=data,timeout=20)
        body=response.json()
        if response.status_code==200 and body.get('ok') is True and body.get('result') is True:return
        # Exact prior owned message only: already absent/unpinned is complete.
        if (method=='unpinChatMessage' and response.status_code==400 and body.get('ok') is False
                and str(body.get('description','')).lower() in
                ('bad request: message to unpin not found','bad request: message is not pinned')):
            return
    except Exception:
        pass
    raise ValueError('Telegram '+method+' not confirmed; known-message retry only')


def _require_pin_rights(session,token,chat,bot_id):
    """Read-only preflight before a NEW photo, never a replacement for ACKs."""
    try:
        response=session.get(f'https://api.telegram.org/bot{token}/getChatMember',
                             params={'chat_id':chat,'user_id':bot_id},timeout=15)
        body=response.json();member=body.get('result')
        if (response.status_code!=200 or body.get('ok') is not True or not isinstance(member,dict)
                or not isinstance(member.get('user'),dict) or member['user'].get('is_bot') is not True
                or type(member['user'].get('id')) is not int or member['user']['id']!=bot_id
                or not (member.get('status')=='creator' or
                    (member.get('status')=='administrator' and member.get('can_pin_messages') is True))):
            raise ValueError()
    except Exception:
        raise ValueError('Telegram pin permission not verified; no new photo sent') from None


def send_once(item, image, text, values, session, state=STATE, persist=None, *, resume=None, previous=None):
    token = values.get('TELEGRAM_BOT_TOKEN')
    chat = values.get('TELEGRAM_CHAT_ID')
    topic = int(values.get('TELEGRAM_EARNINGS_THREAD_ID') or 0)
    if not token or not chat or topic<=0:
        raise ValueError('Telegram credentials or dedicated earnings topic missing')
    if not re.fullmatch('-?[0-9]+',str(chat)):
        raise ValueError('Weekly destination requires a numeric chat identity')
    if previous:validate_record(previous,previous.get('week'))
    state.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(state,timeout=30) as db:
        db.execute('CREATE TABLE IF NOT EXISTS deliveries (week TEXT PRIMARY KEY,status TEXT,source TEXT,message_id INTEGER)')
        if 'receipt_json' not in {r[1] for r in db.execute('PRAGMA table_info(deliveries)')}:
            db.execute('ALTER TABLE deliveries ADD COLUMN receipt_json TEXT')
            db.commit()
        db.execute('BEGIN IMMEDIATE')
        prior=db.execute('SELECT status,message_id,receipt_json FROM deliveries WHERE week=?',(item['week'],)).fetchone()
        record=validate_record(resume,item['week']) if resume else (
            json.loads(prior[2]) if prior and prior[2] else {'week':item['week'],'status':prior[0]} if prior else None)
        if record and record['status']=='sent':
            return {'status':'already_sent_pin_unknown','week':item['week']}
        if record and record['status']=='sending':
            raise ValueError('Previous send outcome uncertain; inspect topic before retrying')
        if record:validate_record(record,item['week'])
        def save(receipt):
            validate_record(receipt,item['week'])
            db.execute('INSERT INTO deliveries(week,status,source,message_id,receipt_json) VALUES(?,?,?,?,?) '
                       'ON CONFLICT(week) DO UPDATE SET status=excluded.status,message_id=excluded.message_id,receipt_json=excluded.receipt_json',
                       (item['week'],receipt['status'],item.get('source_url',''),receipt.get('message_id'),json.dumps(receipt)))
            db.commit()
            if persist:persist(receipt)  # ACK persisted before any pin operation.
        # Release local claim read before read-only bot identity request.
        db.commit()
        bot_id=_bot_id(token,session)
        binding=destination_binding(bot_id,chat,topic)
        if record and record['status'] in ('pin_pending','pinned'):
            if record['destination_binding']!=binding:
                raise ValueError('Known-message destination binding changed; manual review required')
            if record['status']=='pinned' and not record.get('previous_pin'):
                return {'status':'already_pinned','week':item['week']}
        else:
            _require_pin_rights(session,token,chat,bot_id)
            # Recheck under the local write lock: concurrent callers cannot send.
            db.execute('BEGIN IMMEDIATE')
            current=db.execute('SELECT status FROM deliveries WHERE week=?',(item['week'],)).fetchone()
            if current and current[0]!='retryable':
                raise ValueError('Previous send outcome uncertain; inspect topic before retrying')
            record={'schema_version':2,'week':item['week'],'status':'sending'}
            save(record)  # Local and remote compare-and-swap before photo send.
            try:
                response = session.post(f'https://api.telegram.org/bot{token}/sendPhoto',
                    data={'chat_id':chat,'message_thread_id':topic,'caption':telegram_text(text, limit=1024)},
                    files={'photo':('earnings.png',image,'image/png')},timeout=45)
                result = response.json()
            except Exception:
                raise ValueError('Telegram delivery uncertain; inspect dedicated topic, no automatic resend') from None
            if not isinstance(result,dict) or result.get('ok') is not True:
                if (isinstance(result,dict) and result.get('ok') is False and type(response.status_code) is int
                        and 400<=response.status_code<500):
                    save({'schema_version':2,'week':item['week'],'status':'retryable'})
                raise ValueError('Telegram refused delivery or ACK uncertain; no blind retry')
            message=result.get('result')
            if (response.status_code!=200 or not isinstance(message,dict)
                    or type(message.get('message_id')) is not int or message['message_id']<=0
                    or not isinstance(message.get('chat'),dict) or type(message['chat'].get('id')) is not int
                    or message['chat']['id']!=int(chat)
                    or type(message.get('message_thread_id')) is not int or message['message_thread_id']!=topic
                    or not isinstance(message.get('from'),dict) or type(message['from'].get('id')) is not int
                    or message['from']['id']!=bot_id or message['from'].get('is_bot') is not True
                    or not isinstance(message.get('photo'),list) or not message['photo']):
                raise ValueError('Telegram photo ACK identity not verified; no automatic resend')
            record={'schema_version':2,'week':item['week'],'status':'pin_pending',
                    'message_id':message['message_id'],'destination_binding':binding}
            if previous:
                if (previous['status']=='pinned' and previous['destination_binding']==binding
                        and previous['week']==(date.fromisoformat(item['week'])-timedelta(days=7)).isoformat()):
                    record['previous_pin']={k:previous[k] for k in ('week','message_id','destination_binding')}
            save(record)
        if record['status']=='pin_pending':
            # Re-CAS a resumed claim, so a stale concurrent runner stops before pin.
            if (prior and prior[0]=='pin_pending') or resume:save(record)
            _pin_request(session,token,'pinChatMessage',chat,record['message_id'],silent=True)
            record={**record,'status':'pinned'}
            save(record)
        old=record.get('previous_pin')
        if old:
            if old['destination_binding']!=binding or old['message_id']==record['message_id']:
                raise ValueError('Previous pin binding not verified; no unpin attempted')
            _pin_request(session,token,'unpinChatMessage',chat,old['message_id'])
            record={k:v for k,v in record.items() if k!='previous_pin'}
            save(record)
        return {'status':'pinned','week':item['week'],'message_id':record['message_id']}


class GitHubDelivery:
    """Public non-secret weekly status with Contents API SHA compare-and-swap.

    A missing/failed completion write leaves 'sending', preventing blind retries.
    Only safe receipts are published; raw destination/bot identities are hashed.
    """
    def __init__(self, week, session):
        self.week = week
        self.session = session
        repo = os.environ['GITHUB_REPOSITORY']
        if not re.fullmatch(r'[\w.-]+/[\w.-]+', repo):
            raise ValueError('Invalid repository')
        self.url = f'https://api.github.com/repos/{repo}/contents/earnings/{week}.json'
        self.headers = {'Authorization': 'Bearer '+os.environ['GH_TOKEN'],
                        'Accept': 'application/vnd.github+json'}
        self.sha = None

    def read(self):
        r = self.session.get(self.url, headers=self.headers,
                             params={'ref':'earnings-state'}, timeout=30)
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise ValueError(f'Cloud state read failed: HTTP {r.status_code}')
        payload = r.json()
        self.sha = payload['sha']
        record = json.loads(base64.b64decode(payload['content']))
        return validate_record(record,self.week)

    def write(self, record):
        if isinstance(record,str):record={'week':self.week,'status':record}
        validate_record(record,self.week)
        content=json.dumps(record)+'\n'
        payload = {'message':f'Earnings {self.week}: {record["status"]}', 'branch':'earnings-state',
                   'content':base64.b64encode(content.encode()).decode()}
        if self.sha:
            payload['sha'] = self.sha
        r = self.session.put(self.url, headers=self.headers, json=payload, timeout=30)
        if r.status_code not in (200,201):
            raise ValueError(f'Cloud state write failed: HTTP {r.status_code}; no blind retry')
        self.sha = r.json()['content']['sha']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--send',action='store_true')
    parser.add_argument('--github',action='store_true',help='Use durable GitHub delivery state')
    args=parser.parse_args()
    now=datetime.now(ZoneInfo('Asia/Jerusalem'))
    if args.send and not delivery_window(now):
        raise ValueError('Outside weekly delivery window: Friday 18:00 through Sunday, Asia/Jerusalem')
    with requests.Session() as session:
        week=next_monday(now.date())
        values={**dotenv_values(ROOT/'.env'), **os.environ}
        cloud=GitHubDelivery(week.isoformat(),session) if args.github and args.send else None
        prior=None;previous=None
        if cloud:
            prior=cloud.read()
            if prior and prior['status']=='sent':
                print(json.dumps({'status':'already_sent_pin_unknown','week':week.isoformat()}))
                return
            if prior and prior['status']=='sending':
                raise ValueError('Cloud delivery uncertain; inspect topic before retrying')
            if prior and prior['status'] in ('pin_pending','pinned'):
                result=send_once({'week':week.isoformat()},None,None,values,session,
                                 persist=cloud.write,resume=prior)
                print(json.dumps(result,ensure_ascii=True))
                return
            previous=GitHubDelivery((week-timedelta(days=7)).isoformat(),session).read()
        item=fetch_calendar(week,session)
        image=photo_bytes(item['image_url'],session)
        if args.send:
            result=send_once(item,image,caption(item,values.get('TELEGRAM_COMMUNITY_URL') or ''),values,session,
                             persist=cloud.write if cloud else None,previous=previous)
        else:
            result={**item,'status':'preview','image_bytes':len(image)}
    print(json.dumps(result,ensure_ascii=True))


if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        # Never print requests exceptions containing bot-token URLs.
        print(json.dumps({'status':'error','error':str(exc) if isinstance(exc,ValueError) else type(exc).__name__}))
        raise SystemExit(1)
