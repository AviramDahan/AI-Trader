# Optional Telegram news reader

Install `.venv/Scripts/python -m pip install -r service/requirements-telegram-reader.txt`.
Store TELEGRAM_API_ID and TELEGRAM_API_HASH only in the ignored local .env.
Run `.venv/Scripts/python scripts/login_telegram_reader.py` and scan its local QR page.
The ignored .runtime/telegram-reader.session grants account access: protect it like a password.
The login helper restricts Windows permissions and creates a current-user DPAPI encrypted backup.

Set TELEGRAM_NEWS_READER_ENABLED=true and TELEGRAM_NEWS_SOURCE_CHANNELS=financialjuice,WalterBloomberg.
Restart the backend. Its existing news worker polls by default every 300 seconds; Ollama analysis
and paper-price monitoring run separately. No personal dialogs are enumerated, channels joined,
or messages sent by the reader account. Only public broadcast allowlist entries are read.
The existing bot/outbox publishes qualifying translated economic news to the general-news topic.

Sources: https://t.me/financialjuice and https://t.me/WalterBloomberg.
These are relay channels, not independently verified primary publishers. Internal provenance links to
the actual Telegram post, not an invented original article. Outgoing Telegram bulletins omit the
source channel name/link by operator preference; database provenance is retained. Republication permission is supplied
by the operator; access does not itself establish a license. Telegram API use is free, subject to
https://core.telegram.org/api/terms and dynamic flood limits.

Bootstrap reads at most 30 posts/channel, only from the last hour. Subsequent cycles read up to
50 unread posts/channel, oldest first, using database checkpoints. Posts older than six hours
are skipped. Flood waits retain cursors and postpone the affected channel without blocking others.
Existing URL/title deduplication applies; differently worded reports of the same event can still
be distinct. Edits/deletions and media-only posts are not synchronized. This is periodic coverage,
not a complete real-time feed. AI summaries are interpretations of post text, not verification.
Disable TELEGRAM_NEWS_READER_ENABLED to stop collection. No trading behavior is changed.
