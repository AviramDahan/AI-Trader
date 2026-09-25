"""Weekly official Earnings Whispers image; local secrets, durable send guard.

Default is a read-only preview. --send is used by the Friday scheduled task.
Permission to redistribute the chart was confirmed by the owner on 2026-09-25.
"""
from __future__ import annotations

import argparse
import base64
import os
from datetime import datetime, timedelta, date
from io import BytesIO
import json
from pathlib import Path
import re
import sqlite3
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from dotenv import dotenv_values
from PIL import Image
import requests

ROOT = Path(__file__).resolve().parents[1]
FEED = 'https://www.reddit.com/r/EarningsWhisper/new/.rss'
STATE = ROOT / '.runtime' / 'weekly_earnings.sqlite'
HEADERS = {'User-Agent': 'AI-Trader earnings calendar/1.0'}
NS = {'a': 'http://www.w3.org/2005/Atom'}


def next_monday(today: date) -> date:
    return today + timedelta(days=7-today.weekday())


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
    text = (f"דוחות השבוע הבא | {start:%d.%m.%Y}–{end:%d.%m.%Y}\n\n"
            "חברות בולטות הצפויות לדווח:\n" + ' · '.join(item['tickers'][:30]) +
            "\n\nהלוח מציג מבחר מדווחות, לא את כולן. מועדים עשויים להשתנות.\n"
            "Before Open = לפני הפתיחה; After Close = אחרי הסגירה בארה״ב.\n\n"
            "מקור ותמונה: Earnings Whispers — הופץ באישור\n" + item['source_url'])
    if community.startswith('https://t.me/') and len(community)<150:
        text += '\n\nלהצטרפות לקהילה:\n'+community
    if len(text.encode('utf-16-le'))//2 > 1024:
        raise ValueError('Caption exceeds Telegram limit')
    return text


def send_once(item, image, text, values, session, state=STATE, persist=None):
    token = values.get('TELEGRAM_BOT_TOKEN')
    chat = values.get('TELEGRAM_CHAT_ID')
    topic = int(values.get('TELEGRAM_EARNINGS_THREAD_ID') or 0)
    if not token or not chat or topic<=0:
        raise ValueError('Telegram credentials or dedicated earnings topic missing')
    state.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(state,timeout=30) as db:
        db.execute('CREATE TABLE IF NOT EXISTS deliveries (week TEXT PRIMARY KEY,status TEXT,source TEXT,message_id INTEGER)')
        db.execute('BEGIN IMMEDIATE')
        prior = db.execute('SELECT status FROM deliveries WHERE week=?',(item['week'],)).fetchone()
        if prior:
            if prior[0]=='sent':
                return {'status':'already_sent','week':item['week']}
            raise ValueError('Previous send outcome uncertain; inspect topic before retrying')
        db.execute('INSERT INTO deliveries VALUES (?,?,?,NULL)',(item['week'],'sending',item['source_url']))
        db.commit()
        if persist:
            persist('sending')  # Durable cloud claim BEFORE contacting Telegram.
        try:
            response = session.post(f'https://api.telegram.org/bot{token}/sendPhoto',
                data={'chat_id':chat,'message_thread_id':topic,'caption':text},
                files={'photo':('earnings.png',image,'image/png')},timeout=45)
            result = response.json()
        except Exception:
            # A timeout may follow a successful send. Never retry blindly.
            raise ValueError('Telegram delivery uncertain; inspect dedicated topic, no automatic resend') from None
        if not result.get('ok'):
            if 400<=response.status_code<500:
                db.execute('DELETE FROM deliveries WHERE week=?',(item['week'],));db.commit()
                if persist:
                    persist('retryable')
            raise ValueError(f'Telegram refused delivery: HTTP {response.status_code}')
        mid=int(result['result']['message_id'])
        db.execute("UPDATE deliveries SET status='sent',message_id=? WHERE week=?",(mid,item['week']));db.commit()
        if persist:
            persist('sent')
        return {'status':'sent','week':item['week'],'message_id':mid,'topic_id':topic}


class GitHubDelivery:
    """Public non-secret weekly status with Contents API SHA compare-and-swap.

    A missing/failed completion write leaves 'sending', preventing blind retries.
    Only status/week are published; no Telegram credentials or destination IDs.
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
        if record.get('week') != self.week or record.get('status') not in ('sent','sending','retryable'):
            raise ValueError('Invalid cloud delivery state')
        return record['status']

    def write(self, status):
        record = json.dumps({'week':self.week,'status':status})+'\n'
        payload = {'message':f'Earnings {self.week}: {status}', 'branch':'earnings-state',
                   'content':base64.b64encode(record.encode()).decode()}
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
    if args.send and now.weekday()!=4:
        raise ValueError('Automatic delivery is Friday-only in Asia/Jerusalem')
    with requests.Session() as session:
        week=next_monday(now.date())
        cloud=GitHubDelivery(week.isoformat(),session) if args.github and args.send else None
        if cloud:
            prior=cloud.read()
            if prior=='sent':
                print(json.dumps({'status':'already_sent','week':week.isoformat()}))
                return
            if prior=='sending':
                raise ValueError('Cloud delivery uncertain; inspect topic before retrying')
        item=fetch_calendar(week,session)
        image=photo_bytes(item['image_url'],session)
        if args.send:
            values={**dotenv_values(ROOT/'.env'), **os.environ}
            result=send_once(item,image,caption(item,values.get('TELEGRAM_COMMUNITY_URL') or ''),values,session,
                             persist=cloud.write if cloud else None)
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
