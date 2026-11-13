"""Exact previous deployed selector, extracted with ast.get_source_segment.

Obtained locally from git show of the immutable base below. This committed
fixture allows a shallow CI checkout to execute the real old selector without
network/history fetching. It is not a full old-binary/container proof.
"""
BASE_SHA = '2d72146ca70afb27329492fc856987282fc1f32e'
ORIGINAL_BLOB_SHA256 = '5b46b164778db6e63a03821e31fe268eb915988961cab0cd29d67d9b2f66defd'
FUNCTION_SHA256 = 'c7b046484e6681070c8959f6ebb0d67eadad87becda78e3e312deda415e5fe42'
SOURCE = r'''def _claim_telegram_outbox(limit: int = 20, lease_seconds: int = 300) -> list[dict[str, Any]]:
    """Atomically lease due messages so concurrent workers cannot double-send."""
    stamp = now_z()
    lease_until = (parse_time(stamp) + timedelta(seconds=lease_seconds)).isoformat().replace("+00:00", "Z")
    conn = get_db_connection(); cur = conn.cursor(); begin_write_transaction(cur)
    # Community conversation sends have no idempotency token at Telegram.
    # A crashed sender may already have delivered: never reclaim for resending.
    cur.execute("""UPDATE scanner_telegram_outbox SET status='failed',
        last_error='community_delivery_unknown_manual_review'
        WHERE status IN ('sending','community_sending') AND next_attempt_at<=? AND event_type='community_discussion'""", (stamp,))
    # This notification has no remote idempotency token either. A crash after
    # acceptance is UNKNOWN, never an excuse to send the same post again.
    cur.execute("""UPDATE scanner_telegram_outbox SET status='failed',
        last_error='trump_truth_delivery_unknown_manual_review'
        WHERE status IN ('sending','trump_sending') AND next_attempt_at<=? AND event_type='trump_truth_post'""", (stamp,))
    cur.execute("""UPDATE scanner_telegram_outbox
        SET status='retry',next_attempt_at=?,last_error='stale_dispatch_lease_recovered'
        WHERE status='sending' AND next_attempt_at<=?""", (stamp, stamp))
    if using_postgres():
        cur.execute("""WITH due AS (
            SELECT id FROM scanner_telegram_outbox
            WHERE status IN ('pending','retry','community_pending','trump_pending','trump_retry') AND next_attempt_at<=?
            ORDER BY id LIMIT ? FOR UPDATE SKIP LOCKED)
            UPDATE scanner_telegram_outbox o SET status=CASE WHEN o.event_type='community_discussion' THEN 'community_sending' WHEN o.event_type='trump_truth_post' THEN 'trump_sending' ELSE 'sending' END,next_attempt_at=?,last_error=NULL
            FROM due WHERE o.id=due.id RETURNING o.*""", (stamp, limit, lease_until))
        rows = [dict(row) for row in cur.fetchall()]
        conn.commit(); conn.close()
        return rows
    cur.execute("""SELECT * FROM scanner_telegram_outbox
        WHERE status IN ('pending','retry','community_pending','trump_pending','trump_retry') AND next_attempt_at<=?
        ORDER BY id LIMIT ?""", (stamp, limit))
    rows = [dict(row) for row in cur.fetchall()]
    if rows:
        placeholders = ",".join("?" for _ in rows)
        cur.execute(f"""UPDATE scanner_telegram_outbox
            SET status=CASE WHEN event_type='community_discussion' THEN 'community_sending' WHEN event_type='trump_truth_post' THEN 'trump_sending' ELSE 'sending' END,next_attempt_at=?,last_error=NULL
            WHERE id IN ({placeholders}) AND status IN ('pending','retry','community_pending','trump_pending','trump_retry')""",
                    (lease_until, *(row["id"] for row in rows)))
    conn.commit(); conn.close()
    return rows'''
