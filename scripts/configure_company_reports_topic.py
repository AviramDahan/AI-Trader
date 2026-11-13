"""Create only the requested company reports topic; never send/replay notices.

Run inside the configured Telegram service. The durable intent marker prevents
an ambiguous create response from making a duplicate on retry. The operator
copies its private thread_id into TELEGRAM_COMPANY_REPORTS_THREAD_ID for release.
"""
import json
import os
from pathlib import Path

import requests

NAME = '📊 דיווחי חברות'
ENV = 'TELEGRAM_COMPANY_REPORTS_THREAD_ID'


def provision(call, marker, existing=''):
    state = json.loads(marker.read_text()) if marker.exists() else {}
    thread = str(existing or state.get('thread_id', ''))
    if thread.isdigit() and int(thread) > 0:
        call('editForumTopic', message_thread_id=int(thread), name=NAME)
        return int(thread)
    if state:
        raise RuntimeError('ambiguous_create_requires_topic_inspection')
    # Exclusive creation: no parallel creator and no silent retry after timeout.
    with marker.open('x', encoding='utf-8') as handle:
        os.chmod(marker, 0o600)
        json.dump({'state': 'creating'}, handle)
        handle.flush()
        os.fsync(handle.fileno())
    result = call('createForumTopic', name=NAME, icon_color=7322096)
    thread = result.get('message_thread_id')
    if type(thread) is not int or thread <= 0:
        raise RuntimeError('invalid_topic_response')
    temporary = marker.with_suffix('.tmp')
    with temporary.open('x', encoding='utf-8') as handle:
        os.chmod(temporary, 0o600)
        json.dump({'state': 'created', 'thread_id': thread}, handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, marker)
    return thread


def main():
    import config  # Loads existing *_FILE secrets, never prints them.
    session = requests.Session()
    session.trust_env = False
    token, chat = os.environ['TELEGRAM_BOT_TOKEN'], os.environ['TELEGRAM_CHAT_ID']

    def call(method, **fields):
        try:
            response = session.post('https://api.telegram.org/bot'+token+'/'+method,
                                    json={'chat_id': chat, **fields}, timeout=20)
            payload = response.json()
        except (requests.RequestException, ValueError):
            raise RuntimeError('telegram_transport_unknown_no_retry') from None
        if not payload.get('ok'):
            if method == 'editForumTopic' and 'not modified' in str(payload.get('description', '')).lower().replace('_', ' '):
                return True
            raise RuntimeError('telegram_operation_failed')
        return payload['result']

    group = call('getChat')
    if group.get('type') != 'supergroup' or not group.get('is_forum'):
        raise RuntimeError('configured_target_not_forum')
    me = call('getMe')
    member = call('getChatMember', user_id=me['id'])
    if member.get('status') not in {'creator', 'administrator'} or not member.get('can_manage_topics'):
        raise RuntimeError('manage_topics_permission_required')
    marker = Path('/app/.runtime/company-reports-topic.json')
    provision(call, marker, os.getenv(ENV, '').strip())
    print(json.dumps({'topic_ready': True, 'name': NAME, 'messages_sent': 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()
