"""Use one native Telegram icon per topic and plain text titles."""
from dotenv import dotenv_values
import requests
from configure_telegram_topics import ENV_FILE, _request_json


def main():
    env = dotenv_values(ENV_FILE)
    session = requests.Session()
    session.trust_env = False
    base = 'https://api.telegram.org/bot' + env['TELEGRAM_BOT_TOKEN']
    def call(method, data):
        _, payload = _request_json(session, base, method, data)
        if payload.get('ok'):
            return payload['result']
        if 'not modified' in str(payload.get('description', '')).lower().replace('_', ' '):
            return None
        raise RuntimeError('Telegram operation failed: ' + method)
    icons = {x['emoji']: x['custom_emoji_id'] for x in call('getForumTopicIconStickers', {})}
    rows = [
        ('TELEGRAM_MARKET_NEWS_THREAD_ID', 'חדשות שוק', '📰'),
        ('TELEGRAM_PERSONAL_NEWS_THREAD_ID', 'חדשות התיק והמעקב', '💼'),
        ('TELEGRAM_STOCK_NEWS_THREAD_ID', 'חדשות מניות חשובות', '🔎'),
        ('TELEGRAM_PORTFOLIO_THREAD_ID', 'מצב תיק דמו', '💼'),
        ('TELEGRAM_SIGNALS_THREAD_ID', 'סיגנלים', '📈'),
        ('TELEGRAM_TRADES_THREAD_ID', 'עסקאות דמו', '💱'),
    ]
    for key, name, emoji in rows:
        call('editForumTopic', {'chat_id': env['TELEGRAM_CHAT_ID'], 'message_thread_id': env[key],
                               'name': name, 'icon_custom_emoji_id': icons[emoji]})
    # General has its own fixed Telegram icon.
    call('editGeneralForumTopic', {'chat_id': env['TELEGRAM_CHAT_ID'], 'name': 'צאט כללי'})
    print('Updated six topic icons and seven plain titles; no messages deleted.')


if __name__ == '__main__':
    main()
