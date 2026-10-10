Telegram: the existing live activity view
========================================

The community launches the SAME published dashboard at::

    https://aviramdahan.github.io/AI-Trader/market/?miniapp=1

The single launch parameter selects the live tab by default and avoids URL
ampersand escaping in BotFather. Normal website entry still defaults to signals.

No extra website, worker, scanner, schema, feed or polling loop is added.
The existing bounded public GETs remain unchanged. Telegram launch data is
not parsed, logged, stored, forwarded or used for identity/API authorization.
The Mini App entry never receives the browser's saved operator token; the
normal website's operator access is unchanged. The default language is Hebrew
only when no language preference was saved. Reduced-motion controls are intact.

Telegram-only bootstrap loads the fixed official SDK when BOTH the Mini App
entry marker and Telegram platform/version fragment exist. This is a display
hint, NOT authentication. Ordinary visits do not load the SDK. On mount it
calls ready/expand and observes stable viewport/safe area changes. Optional
SDK failures do not prevent the normal responsive website. No permission,
contact, write-access, payment, arbitrary URL or chat-reading API is used.

Operator setup (one time, never from a recurring worker)
------------------------------------------------------

Use the existing bot, verified by getMe, and its verified BotFather owner
session. Configure Main Mini App with the HTTPS URL above. Configure its
default ChatMenuButton as web_app, text "המערכת בלייב", URL above. Read it
back with getChatMenuButton. The menu button is for the bot's PRIVATE chat;
it is not a web_app button in a forum group (Telegram restricts that type).
For the community, use a normal inline URL button linking to::

    https://t.me/<verified-existing-bot-username>?startapp=live

This launches the configured Main Mini App in the current chat. Publish one
real community entry notice and pin quietly; do not post recurring activity
messages or reset/replace topic infrastructure. Inspect recent notices first
and read back the posted message/button; on uncertain send, inspect rather
than retry blindly. Never include bot tokens, chat IDs or session data in Git.

Updates follow the existing CI/Readiness/Pages deployment once; Telegram loads
that published URL on reopening. An already open WebView can retain its loaded
bundle until reopened; this is not instantaneous hot replacement of code.

Rollback: restore the recorded prior default menu and prior Main Mini App
configuration, and revert only the frontend changes through normal release.
No trading/database restore is required. Do not alter the regular deploy or
schema protections. Actual Android/iOS rendering needs real client observation;
synthetic SDK tests alone are not proof of a live Telegram WebView.

Tests: npm run test:activity, npm run test:research, node
test-signal-presentation.cjs, npm run build. The integration tests mock the
SDK and do not send messages or execute trading operations.
