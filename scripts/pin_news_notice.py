"""Publish/pin one source-quality notice per news topic. Local secrets only."""
from pathlib import Path
import sqlite3
import requests
from dotenv import dotenv_values
from configure_telegram_topics import _request_json

ROOT = Path(__file__).resolve().parents[1]
NOTICE = (
    'מידע על החדשות בטופיק\n\n'
    'הידיעות עשויות לכלול תרגום או תקציר בעזרת AI, על בסיס כותרת, תקציר או הודעת מקור בלבד — '
    'לא בהכרח הכתבה המלאה. ייתכנו טעויות, ולא כל דיווח אומת מול מקור ראשוני.\n\n'
    'ייחוס לדיווח והסתייגויות מהותיות יישמרו בגוף הידיעה. '
    'פרשנות AI אינה עובדה מאומתת. החדשות הן מידע בלבד, לא המלצת השקעה או הוראת מסחר.'
)


def main():
    values = dotenv_values(ROOT / '.env')
    base = 'https://api.telegram.org/bot' + values['TELEGRAM_BOT_TOKEN']
    chat = values['TELEGRAM_CHAT_ID']
    topics = sorted({int(values[key]) for key in (
        'TELEGRAM_MARKET_NEWS_THREAD_ID', 'TELEGRAM_PERSONAL_NEWS_THREAD_ID',
        'TELEGRAM_STOCK_NEWS_THREAD_ID')})
    with sqlite3.connect(ROOT / '.runtime/news-notices.sqlite') as db, requests.Session() as session:
        db.execute('CREATE TABLE IF NOT EXISTS notices(chat TEXT,topic INTEGER,message_id INTEGER, PRIMARY KEY(chat,topic))')
        for topic in topics:
            row = db.execute('SELECT message_id FROM notices WHERE chat=? AND topic=?',(chat,topic)).fetchone()
            if row and row[0] is None:
                raise RuntimeError('Prior send outcome uncertain: inspect topic before retrying')
            if not row:
                db.execute('INSERT INTO notices VALUES (?,?,NULL)',(chat,topic)); db.commit()
                _, result = _request_json(session,base,'sendMessage',{
                    'chat_id':chat,'message_thread_id':topic,'text':NOTICE,'disable_notification':True})
                if not result.get('ok'):
                    raise RuntimeError('Telegram rejected notice; inspect before retrying')
                mid = result['result']['message_id']
                db.execute('UPDATE notices SET message_id=? WHERE chat=? AND topic=?',(mid,chat,topic)); db.commit()
            else:
                mid = row[0]
            _, result = _request_json(session,base,'pinChatMessage',{
                'chat_id':chat,'message_id':mid,'disable_notification':True})
            if not result.get('ok'):
                raise RuntimeError('Telegram rejected pin')
            print(f'topic={topic} notice={mid} pinned=true')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Do not allow token-bearing HTTP exception URLs into logs.
        print('Notice setup failed: '+type(exc).__name__)
        raise SystemExit(1)
