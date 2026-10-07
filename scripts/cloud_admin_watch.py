"""External deterministic health probe: no LLM, private Telegram destination only."""
import json,os,time
import sys
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import Request,urlopen
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'service'/'server'))
from admin_messages import timestamped
from telegram_presentation import telegram_text

def main():
    state_path=Path('.admin-watch/state.json')
    state_path.parent.mkdir(exist_ok=True)
    state=json.loads(state_path.read_text()) if state_path.exists() else {'failed':False}
    failed=False
    try:
        with urlopen(os.environ['BACKEND_URL'].rstrip('/')+'/api/scanner/dashboard',timeout=30) as r:
            data=json.load(r)
        assert data['paper_only'] and data['lifecycle_verification']['accounting_ok']
        services={s['component']:s for s in data['services']}
        assert services['monitor']['status']!='error'
        for component,max_age in [('monitor',900),('backup',7500),('telegram',300)]:
            stamp=services[component]['last_success_at']
            assert (datetime.now(timezone.utc)-datetime.fromisoformat(stamp.replace('Z','+00:00'))).total_seconds()<max_age
    except Exception:failed=True
    if failed and not state['failed']:
        token=os.environ['TELEGRAM_ADMIN_BOT_TOKEN']
        chat=os.environ['TELEGRAM_ADMIN_CHAT_ID']
        event_time=datetime.now(timezone.utc)
        payload=json.dumps({'chat_id':chat,'text':telegram_text(timestamped('AI-Trader Admin\nבדיקת הבריאות החיצונית נכשלה: שרת/API/DB/ניטור/גיבוי. נדרשת בדיקה. אין שינוי אוטומטי לעסקאות.',event_time))}).encode()
        request=Request('https://api.telegram.org/bot'+token+'/sendMessage',data=payload,headers={'Content-Type':'application/json'})
        try:
            with urlopen(request,timeout=15) as r:assert json.load(r)['ok']
        except Exception:
            print('Private alert delivery failed; no public fallback')
            return
    state_path.write_text(json.dumps({'failed':failed,'checked_at':time.time()}))
    print('Health: FAIL' if failed else 'Health: PASS')

if __name__=='__main__':main()
