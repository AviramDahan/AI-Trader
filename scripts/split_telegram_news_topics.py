"""Non-destructive, repeatable split of portfolio/watchlist and broad stock news."""
from dotenv import dotenv_values
import requests
from configure_telegram_topics import ENV_FILE, _request_json, _write_env


def main():
    values = dotenv_values(ENV_FILE)
    token, chat = values.get('TELEGRAM_BOT_TOKEN'), values.get('TELEGRAM_CHAT_ID')
    stock = values.get('TELEGRAM_STOCK_NEWS_THREAD_ID')
    if not token or not chat or not stock:
        raise RuntimeError('Configure existing Telegram forum first')
    session = requests.Session()
    session.trust_env = False
    def call(method, data):
        response, payload = _request_json(session, f'https://api.telegram.org/bot{token}', method,
                                          {'chat_id': chat, **data})
        if payload.get('ok'):
            return payload['result']
        if method == 'editForumTopic' and 'not modified' in str(payload.get('description', '')).lower().replace('_', ' '):
            return True
        raise RuntimeError('Telegram topic operation failed: ' + method)
    personal = values.get('TELEGRAM_PERSONAL_NEWS_THREAD_ID')
    if not personal:
        result = call('createForumTopic', {'name': '💼 חדשות התיק והמעקב', 'icon_color': 16766590})
        personal = str(result['message_thread_id'])
        _write_env({'TELEGRAM_PERSONAL_NEWS_THREAD_ID': personal})
    call('editForumTopic', {'message_thread_id': personal, 'name': '💼 חדשות התיק והמעקב'})
    call('editForumTopic', {'message_thread_id': stock, 'name': '🔎 חדשות מניות חשובות'})
    print('News topics split; existing messages preserved. Personal topic:', personal)


if __name__ == '__main__':
    main()
