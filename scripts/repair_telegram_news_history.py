"""Reviewed, source-grounded corrections to specific bot news; no trading writes.

Dry run by default. Archives original bot messages locally before any edit.
No bulk chat cleanup, no account/session details in output.
"""
import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import dotenv_values
from telethon import TelegramClient

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'service/server'))
import database
from news_pipeline import _publication_time_he
from telegram_topics import with_news_community_link

# Reviewed against the stored original headline, not the former AI summary.
CORRECTIONS={
    587: (5035,'Strategy הגדילה את החזקות הביטקוין שלה ב־950 מטבעות. הכותרת עוסקת גם במניית MSTR.'),
    590: (None,'השוואה בין Astera Labs לבין Marvell: איזו מניית טכנולוגיה עדיפה לרכישה ב־2026?'),
    591: (5052,'השוואה בין CrowdStrike לבין Palo Alto: איזו מניית אבטחת סייבר ובינה מלאכותית מצדיקה יותר את שווייה?'),
    593: (5066,'השוואה בין HPE לבין Super Micro: איזו מניית שרתי בינה מלאכותית מציעה יחס סיכון־סיכוי עדיף?'),
    595: (5071,'השוואה בין Dell לבין HPE: איזו מניית שרתי בינה מלאכותית עדיפה לרכישה?'),
    596: (4980,'Dell Technologies: הוגש דיווח בעלות מסוג Form 4 ל־SEC. המטא־דאטה אינו מספיק כדי להסיק השפעה על מחיר המניה.'),
    597: (4979,'Dell Technologies: הוגש דיווח בעלות מסוג Form 4 ל־SEC. המטא־דאטה אינו מספיק כדי להסיק השפעה על מחיר המניה.'),
    598: (4978,'Dell Technologies: הוגש דיווח בעלות מסוג Form 4 ל־SEC. המטא־דאטה אינו מספיק כדי להסיק השפעה על מחיר המניה.'),
    635: (5291,'נשיא איראן נפגש עם ראש ממשלת קטאר בניו יורק; השניים דנו במאמצים להפחתת המתיחות. שני הדיווחים על הפגישה אוחדו כאן.'),
    638: (5298,'שר האוצר היפני קטאיאמה: הוצאות ביטחון נוספות נועדו להתמודד עם האיום מסין.'),
    644: (5296,'לפי שני מקורות, נמלי התעופה בארביל ובסולימאניה שבעיראק משעים טיסות איראניות החל מיום שישי.'),
    671: (5351,'שגריר ארצות הברית בסין: טראמפ ושי קיימו שיחה פתוחה וכנה מאוד, לפי CNBC.'),
    672: (5352,'שגריר ארצות הברית בסין: טראמפ ושי מתחילים לפתח יחסים שיש בהם מידה מסוימת של אמון.'),
    673: (5353,'שגריר ארצות הברית בסין: טראמפ הבהיר שכל סיוע סיני לאיראן אינו מקובל לחלוטין, לפי CNBC.'),
    675: (5355,'Morning Juice — סקירת הכנה למסחר בארצות הברית ל־25 בספטמבר. הכותרת לבדה אינה כוללת פרטי חדשות.'),
    679: (5359,'החוזים העתידיים על גז טבעי בארצות הברית מעמיקים את הירידות: המחירים יורדים ב־5% במסחר תנודתי לקראת פקיעת החוזה.'),
    681: (5364,'שגריר ארצות הברית בסין: אין שינוי במדיניות האמריקאית כלפי טיוואן.'),
    682: (5365,'גולדמן זאקס צופה שחמש חברות התשתיות הטכנולוגיות הגדולות בארצות הברית יגדילו את ההשקעה בתשתיות בינה מלאכותית ב־54%, ל־1.2 טריליון דולר בשנת 2027, מעל תחזיות וול סטריט. זו תחזית, לא הוצאה שכבר בוצעה.'),
}


async def main(apply=False, merge_only=False):
    cfg=dotenv_values(ROOT/'.env')
    http=requests.Session();http.trust_env=False
    base='https://api.telegram.org/bot'+cfg['TELEGRAM_BOT_TOKEN']
    def api(method,fields):
        r=http.post(base+'/'+method,json=fields,timeout=20)
        body=r.json()
        if not body.get('ok') and 'message is not modified' not in body.get('description',''):
            raise RuntimeError('Telegram operation failed: '+str(body.get('error_code')))
        return body
    bot=api('getMe',{})['result']['id']
    client=TelegramClient(str(ROOT/'.runtime/telegram-reader.session'),int(cfg['TELEGRAM_API_ID']),
                          cfg['TELEGRAM_API_HASH'],receive_updates=False,flood_sleep_threshold=0)
    await client.connect()
    try:
        if not await client.is_user_authorized():raise RuntimeError('Reader login required')
        chat=await client.get_entity(int(cfg['TELEGRAM_CHAT_ID']))
        if merge_only:
            # Two reviewed repeat reports, not a per-ticker or daily quota.
            pairs={636:(5292,5291),645:(5297,None),676:(5356,5352),677:(5357,5351),678:(5358,5353)}
            messages=await client.get_messages(chat,ids=list(pairs))
            originals=[]
            for m in messages:
                if not m:continue
                if m.sender_id!=bot:raise RuntimeError('Not an application bot message')
                if m.id==636 and 'ניו יורק' not in m.message:raise RuntimeError('Unexpected message content')
                if m.id==645 and 'Fed' not in m.message:raise RuntimeError('Unexpected message content')
                if m.id in (676,677,678) and 'טראמפ' not in m.message:raise RuntimeError('Unexpected message content')
                originals.append({'id':m.id,'text':m.message})
            print(json.dumps({'merge_messages':[m['id'] for m in originals],'apply':apply}))
            if not apply:return
            archive=ROOT/'.runtime'/('telegram-merged-news-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.json')
            archive.write_text(json.dumps(originals,ensure_ascii=False),encoding='utf-8')
            for m in originals:
                news_id,parent_id=pairs[m['id']]
                conn=database.get_db_connection()
                if parent_id is None:
                    parent_id=conn.execute("SELECT id FROM scanner_news WHERE url='https://t.me/walterbloomberg/35919'").fetchone()['id']
                child=dict(conn.execute('SELECT * FROM scanner_news WHERE id=?',(news_id,)).fetchone())
                parent=dict(conn.execute('SELECT * FROM scanner_news WHERE id=?',(parent_id,)).fetchone())
                links=json.loads(parent.get('alternate_sources_json') or '[]')
                if not any(r.get('url')==child['url'] for r in links):
                    links.append({'url':child['url'],'publisher':child['publisher'],'published_at':child['published_at']})
                conn.execute("UPDATE scanner_news SET alternate_sources_json=? WHERE id=?",(json.dumps(links),parent_id))
                conn.execute("UPDATE scanner_news SET duplicate_of=?,analysis_status='duplicate_event',quality_version=2 WHERE id=?",(parent_id,news_id))
                conn.execute("UPDATE scanner_news_jobs SET status='done',last_error=NULL WHERE news_id=?",(news_id,))
                conn.commit();conn.close()
                api('deleteMessage',{'chat_id':cfg['TELEGRAM_CHAT_ID'],'message_id':m['id']})
                print('Merged repeated bot message',m['id'])
            print('Original-message archive:',archive)
            return
        messages=await client.get_messages(chat,ids=list(CORRECTIONS))
        plan=[]
        conn=database.get_db_connection()
        for m in messages:
            if not m or m.sender_id!=bot:continue
            news_id,translation=CORRECTIONS[m.id]
            links=re.findall(r'https?://[^\s<>]+',m.message or '')
            row=conn.execute('SELECT * FROM scanner_news WHERE id=?',(news_id,)).fetchone() if news_id else None
            if not row or (row['url'] not in links and row['source_kind']!='telegram_post'):
                row=None
                for url in links:
                    row=conn.execute('SELECT * FROM scanner_news WHERE url=?',(url,)).fetchone()
                    if row:break
            if not row:raise RuntimeError('Source missing for message '+str(m.id))
            row=dict(row)
            text=('תיקון תקציר היסטורי — לא ידיעה חדשה\n\n'+translation+
                  '\n\nהתקציר הקודם כלל ניסוח או פרטים שלא אומתו במקור; אין להסתמך עליהם.\n'
                  'התרגום המתוקן מבוסס על הכותרת/מטא־דאטה בלבד. זו אינה המלצת מסחר.\n\n'
                  +'פורסם במקור: '+_publication_time_he(row['published_at']))
            if row.get('source_kind')!='telegram_post':
                text+='\nמקור: '+str(row.get('original_publisher') or row['publisher'])+'\n'+row['url']
            text=with_news_community_link(text,'market_news')
            plan.append((m,row,text,translation))
        conn.close()
        print(json.dumps({'messages':[m.id for m,_,_,_ in plan],'apply':apply}))
        if not apply:return
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        archive=ROOT/'.runtime'/('telegram-news-corrections-'+stamp+'.json')
        archive.write_text(json.dumps([{'id':m.id,'old':m.message,'new':text,'news_id':row['id']}
                                      for m,row,text,_ in plan],ensure_ascii=False),encoding='utf-8')
        for m,row,text,translation in plan:
            api('editMessageText',{'chat_id':cfg['TELEGRAM_CHAT_ID'],'message_id':m.id,'text':text,'disable_web_page_preview':True})
            conn=database.get_db_connection()
            conn.execute("""UPDATE scanner_news SET title_he=?,summary_he=?,interpretation_he=?,
                sentiment='unclear',impact='unclear',materiality='low',relevance=NULL,
                analysis_status='reviewed_source_only',analysis_error=NULL,quality_version=2 WHERE id=?""",
                (translation,translation,'תיקון ידני לפי המקור בלבד; לא נקבעה השפעה על מחיר המניה.',row['id']))
            conn.execute("UPDATE scanner_news_jobs SET status='done',last_error=NULL WHERE news_id=?",(row['id'],))
            conn.commit();conn.close()
            print('Corrected message',m.id)
        print('Original-message archive:',archive)
    finally:await client.disconnect()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');parser.add_argument('--merge-only',action='store_true')
    args=parser.parse_args()
    try:asyncio.run(main(args.apply,args.merge_only))
    except Exception as exc:raise SystemExit(type(exc).__name__+': history repair stopped; no secrets logged')
