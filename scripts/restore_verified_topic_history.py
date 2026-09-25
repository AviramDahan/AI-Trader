"""Restore two existing real records into their current topics, once.

Explicitly historical, not a new trade/news signal. Uses durable outbox and
does not write any account, position, order or fill. --apply is required.
"""
import argparse
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'service/server'))
from database import get_db_connection, begin_write_transaction
from scanner_engine import enqueue_telegram
from news_pipeline import _publication_time_he


def main(apply=False):
    conn=get_db_connection();cur=conn.cursor()
    news=cur.execute("SELECT * FROM scanner_news WHERE id=5057 AND ticker='INTC'").fetchone()
    trade=cur.execute("SELECT * FROM scanner_telegram_outbox WHERE id=244 AND event_type='tp' AND status='sent'").fetchone()
    if not news or not trade or 'TMO' not in trade['message']:
        raise RuntimeError('Reviewed historical evidence is missing; aborting')
    news_text=('השלמת היסטוריית המעקב — לא ידיעה חדשה ולא סיגנל\n\n'
        'מניה במעקב: INTC — Intel\n\n'
        'מניות AMD ו־INTC ממשיכות לעלות, כאשר Muse של Meta מעורר ציפיות לצמיחה בביקוש למעבדים לסוכני בינה מלאכותית.\n\n'
        'תרגום מתוקן של כותרת המקור בלבד; אין להסיק ממנה רווח עתידי או המלצת קנייה.\n\n'
        'פורסם במקור: '+_publication_time_he(news['published_at'])+'\nמקור: '+news['publisher']+'\n'+news['url'])
    trade_text=('השלמת היסטוריית עסקאות דמו — לא ביצוע חדש\n\n'
        'האירוע הבא כבר בוצע ונרשם במסד הנתונים. שחזור ההודעה אינו משנה את התיק.\n'
        'מועד ההתראה המקורית: '+_publication_time_he(trade['sent_at'])+'\n\n'+trade['message'])
    print('Records: existing INTC watchlist headline 5057; existing TMO TP outbox event 244. Apply:',apply)
    if apply:
        begin_write_transaction(cur)
        enqueue_telegram(cur,'history-restore:news:5057:quality2','watchlist_news',news_text)
        enqueue_telegram(cur,'history-restore:trade:244','tp',trade_text)
        conn.commit()
    conn.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true')
    main(parser.parse_args().apply)
