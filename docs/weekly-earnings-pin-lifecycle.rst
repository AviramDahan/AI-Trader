Weekly earnings calendar pin lifecycle
=====================================

The existing official Earnings Whispers source, freshness/author checks,
Friday/weekend delivery window and workflow concurrency are unchanged. The
existing ``EARNINGS_TELEGRAM_THREAD_ID`` secret selects the active company
reports topic. Preview and Monday runs never send or pin.

Before a new photo, read-only ``getMe`` and ``getChatMember`` checks verify the
bot and pin permission, so missing rights cannot knowingly create an unpinnable
photo. Existing pinned receipts still verify the current destination binding
before reporting success, with no source fetch or Telegram mutation.

After a photo send, the publisher validates its Telegram ACK against the
read-only ``getMe`` bot identity, expected numeric chat, exact thread, positive
message ID and actual photo. It persists the known-message receipt locally and
through the existing GitHub Contents compare-and-swap **before** attempting a
silent pin. A pin failure retries only the known message ID; it does not fetch
or resend the image. An unknown photo outcome remains blocked for operator
review. Existing legacy ``sent`` records lacking a verified bound receipt stay
``already_sent_pin_unknown``; they are never replayed or guessed.

The public ``earnings-state`` branch retains one receipt per week at
``earnings/YYYY-MM-DD.json``. Version 2 known-message receipts contain only::

  {
    "schema_version": 2,
    "week": "2026-11-02",
    "status": "pinned",
    "message_id": 123,
    "destination_binding": "<64 lowercase SHA256 hex characters>"
  }

``pin_pending`` has the same fields. ``sending`` is durably claimed before
``sendPhoto``; ``retryable`` is allowed only after an explicit Telegram 4xx
refusal. Neither state authorizes guessing a message ID. The binding is
``SHA256(json.dumps(['weekly-earnings-v2', bot_id, chat_id, thread_id],
separators=(',', ':'), ensure_ascii=True).encode())`` with integer identities;
the script exports ``destination_binding``. Raw chat/thread/bot IDs, usernames
and credentials never enter the public receipt.

A previous verified ``pinned`` receipt is eligible for replacement only for
the immediately prior week with the identical destination binding. After the
new silent pin ACK is durably recorded, the publisher unpins that exact prior
message ID. It never calls unpin-all, scans unrelated pins, deletes a message,
or guesses an older message. Pending cleanup is represented by::

  "previous_pin": {
    "week": "2026-10-26",
    "message_id": 122,
    "destination_binding": "<same binding as current receipt>"
  }

Cleanup failure leaves that exact reference attached to ``pinned`` and a
restart retries only its unpin. Confirmed absence of that known message is
idempotent success. Unrelated permission/errors remain blocked. A changed
destination never unpins the former target.

For a one-time migration outside the delivery window, an operator may copy
the existing verified current-week photo, validate its actual send ACK and
destination, pin it, then seed the current-week ``pinned`` receipt using the
existing state-branch SHA compare-and-swap. This is an explicit operator
action, not an invocation of ``--send`` or a new next-week publication. The
script cannot infer migration success from old ``sent`` metadata.

Regression tests use mocked Telegram/GitHub and disposable SQLite only. They
exercise send/ACK/pin ordering, restart after pin/cleanup failures, ambiguous
send blocking, 4xx retry, CAS rejection, target mismatch, legacy unknown state,
one sender under a concurrent claim, preview and Monday no-send behavior.
These tests do not prove a live Telegram pin or a future scheduled execution.
