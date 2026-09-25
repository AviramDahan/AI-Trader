"""Persist a one-time forward-only activation timestamp; never rewind cursors."""
from datetime import datetime, timezone
from dotenv import dotenv_values
from configure_telegram_topics import ENV_FILE, _write_env

if __name__ == '__main__':
    values = dotenv_values(ENV_FILE)
    key = 'STOCK_SCANNER_EXTENDED_EXITS_FROM'
    if not values.get(key):
        _write_env({key: datetime.now(timezone.utc).isoformat()})
    print('Extended-hours paper TP/SL enabled forward-only; restart backend.')
