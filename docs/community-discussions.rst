Automatic community conversations
=================================

The official bot, not a simulated human, runs only in the singleton cloud
Telegram role. No Codex availability or scheduled thread wakes are required.
Default off. No schema migration, trading controls or news-source changes.

Enable TELEGRAM_COMMUNITY_DISCUSSIONS_ENABLED=true in protected runtime.env
only after deployment/readiness. Optionally enable
TELEGRAM_COMMUNITY_AI_REPLIES_ENABLED=true for the existing news Luna model.
Both flags default false. Disable the first flag to stop polling/new posts and
fence queued community deliveries; existing trading/news outboxes keep running.

Require no webhook or other getUpdates consumer for this bot, and an official
bot administrator in the configured community. Never remove an existing webhook
or consume another bot's updates. This consumer acknowledges updates for this
bot, ignores other chats/topics, and is owned by the Telegram role lease.

An optional SEED_MESSAGE_ID/SEED_AT must refer to a previously actually verified
General discussion in the same community within seven days. Bootstrap does not
resend that discussion, and reserves its local day against a second opener.

Bounds: at most one opener/local day, fresh cached research within six hours,
no automatic follow-ups without new human replies, 10:00-21:00 Israel only.
Same candidate set is not reopened during retained history. Replies only to
tracked bot messages, never private chats, other topics, anonymous senders,
other bots or trading commands. At most eight attempts/day, four/root,
two/user/day, five-minute global cooldown. Multiple human responders in the
same polling batch are left to discuss without another bot intervention.
These are spam bounds, not a quota. A missed/ambiguous reply is not replayed.

State is a bounded 64KiB JSON record in scanner_settings.community_discussions_v1;
root metadata seven days, dispatch claims one day, user hashes per local day,
no user names or stored chat transcripts. Offset and attempts are persisted
before AI. Short dedicated advisory transactions never span network IO or
lock trading admission. Outgoing intent uses the existing deduplicated outbox,
General has no thread field, replies require the original message to exist.
Stale sending leases and ambiguous responses become terminal, never resend.

AI uses existing shared request pacing, monthly $25 cap and payment latch, with
one bounded 220-token request per reserved reply and no repair/retry. It yields
to news queue work and stops at 75% budget usage. No tools/action interface.
Data and human messages are untrusted; unsupported output/numbers/actions fall
back to an educational deterministic question. No price requests, provider
fetches, trades, model changes, fixed-risk sizing or portfolio writes occur.
Community usage is recorded under community_discussion in ai_call_usage, not
misattributed to news analysis or final stock review.

Monitor scanner_service_status.community_discussions and the bounded state
offset/last_poll_at/attempted/delivered/unknown_deliveries. An API send success is
not human readback; no synthetic public message or paid test call is needed.
Binary rollback leaves state/outbox rows intact. Dedicated community_pending and
community_sending statuses are not selected or reclaimed by the previous binary;
its normal pending/retry/sending behavior is unchanged. Disable creation before
rollback; older code cannot drain community JSON as regular messages. Forward
upgrade can expire old intents, not replay unknown deliveries. No DB rewind.
