"""Private alert formatting, independent of application/database initialization."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import re


def timestamped(message, created_at):
    """Render the persisted event time, not the delivery/retry time."""
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    stamp = created_at.astimezone(ZoneInfo('Asia/Jerusalem')).strftime('%d/%m/%Y %H:%M')
    body = re.sub(r'\nTimestamp: [^\n]*$', '', message.rstrip())
    return body + '\nTimestamp: ' + stamp + ' (Israel)'
