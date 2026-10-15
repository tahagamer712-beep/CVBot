"""Referral rewards: 10 referrals = 1 free CV."""
import sqlite3

REWARD_THRESHOLD = 10


def get_referral_stats(db_path, user_id):
    conn = sqlite3.connect(db_path)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM referrals WHERE referrer_id=?",
            (user_id,)).fetchone()[0]
    except Exception:
        count = 0
    try:
        row = conn.execute(
            "SELECT referrals_count, reward_status FROM rewards WHERE user_id=?",
            (user_id,)).fetchone()
        status = row[1] if row else 'locked'
    except Exception:
        status = 'locked'
    conn.close()
    return {'count': count, 'remaining': max(0, REWARD_THRESHOLD - count),
            'status': status}


def check_and_unlock_reward(db_path, user_id):
    """Check if user reached threshold. Idempotent."""
    conn = sqlite3.connect(db_path)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM referrals WHERE referrer_id=?",
            (user_id,)).fetchone()[0]
    except Exception:
        conn.close()
        return False
    if count < REWARD_THRESHOLD:
        conn.close()
        return False
    # Idempotent unlock
    row = conn.execute(
        "SELECT reward_status FROM rewards WHERE user_id=?",
        (user_id,)).fetchone()
    if row and row[0] in ('available', 'in_use', 'used'):
        conn.close()
        return False  # already unlocked
    conn.execute(
        "INSERT INTO rewards (user_id, referrals_count, reward_status, unlocked_at) "
        "VALUES (?,?, 'available', datetime('now')) "
        "ON CONFLICT(user_id) DO UPDATE SET "
        "referrals_count=excluded.referrals_count, "
        "reward_status='available', unlocked_at=datetime('now')",
        (user_id, count))
    conn.commit()
    conn.close()
    return True


def consume_reward(db_path, user_id, order_id):
    """Mark reward as used for an order. Returns False if not available."""
    conn = sqlite3.connect(db_path)
    cur = conn.execute(
        "UPDATE rewards SET reward_status='used', reward_order_id=?, "
        "used_at=datetime('now') WHERE user_id=? AND reward_status='available'",
        (order_id, user_id))
    ok = cur.rowcount > 0
    if ok:
        conn.execute(
            "UPDATE orders SET is_free_reward=1 WHERE order_id=?",
            (order_id,))
    conn.commit()
    conn.close()
    return ok
