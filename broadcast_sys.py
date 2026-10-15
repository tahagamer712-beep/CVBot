"""Broadcast system: admin composes, previews, confirms, sends gradually."""
import sqlite3
import asyncio
import time


def create_broadcast(db_path, admin_id, content_type, content_ref, caption=''):
    conn = sqlite3.connect(db_path)
    cur = conn.execute(
        "INSERT INTO broadcasts (admin_id, content_type, content_ref, caption) "
        "VALUES (?,?,?,?)", (admin_id, content_type, content_ref, caption))
    bid = cur.lastrowid
    # Get all users
    users = conn.execute("SELECT user_id FROM users").fetchall()
    for (uid,) in users:
        conn.execute(
            "INSERT OR IGNORE INTO broadcast_recipients "
            "(broadcast_id, user_id) VALUES (?,?)", (bid, uid))
    conn.execute(
        "UPDATE broadcasts SET target_count=? WHERE id=?",
        (len(users), bid))
    conn.commit()
    conn.close()
    return bid, len(users)


async def send_broadcast(bot, db_path, broadcast_id, rate_limit=0.05):
    """Send gradually. Resumable: skips already-sent."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    bc = conn.execute(
        "SELECT * FROM broadcasts WHERE id=?", (broadcast_id,)).fetchone()
    if not bc or bc['status'] not in ('draft', 'sending'):
        conn.close()
        return None
    conn.execute(
        "UPDATE broadcasts SET status='sending' WHERE id=?", (broadcast_id,))
    conn.commit()

    pending = conn.execute(
        "SELECT user_id FROM broadcast_recipients "
        "WHERE broadcast_id=? AND status='pending'",
        (broadcast_id,)).fetchall()
    conn.close()

    sent = 0
    failed = 0
    for (uid,) in pending:
        try:
            ctype = bc['content_type']
            if ctype == 'text':
                await bot.send_message(chat_id=uid, text=bc['content_ref'],
                                       parse_mode='Markdown')
            elif ctype == 'photo':
                await bot.send_photo(chat_id=uid, photo=bc['content_ref'],
                                     caption=bc['caption'] or None,
                                     parse_mode='Markdown')
            elif ctype == 'video':
                await bot.send_video(chat_id=uid, video=bc['content_ref'],
                                     caption=bc['caption'] or None,
                                     parse_mode='Markdown')
            elif ctype == 'document':
                await bot.send_document(chat_id=uid,
                                        document=bc['content_ref'],
                                        caption=bc['caption'] or None,
                                        parse_mode='Markdown')
            else:
                # Fallback: copy message
                await bot.copy_message(
                    chat_id=uid,
                    from_chat_id=bc['content_ref'].split(':')[0],
                    message_id=int(bc['content_ref'].split(':')[1]))
            # Mark sent
            c2 = sqlite3.connect(db_path)
            c2.execute(
                "UPDATE broadcast_recipients SET status='sent' "
                "WHERE broadcast_id=? AND user_id=?",
                (broadcast_id, uid))
            c2.execute(
                "UPDATE broadcasts SET sent_count=sent_count+1 WHERE id=?",
                (broadcast_id,))
            c2.commit()
            c2.close()
            sent += 1
        except Exception as e:
            err = str(e)[:200]
            # Handle rate limit
            if 'retry_after' in err.lower() or 'flood' in err.lower():
                await asyncio.sleep(2)
            c2 = sqlite3.connect(db_path)
            c2.execute(
                "UPDATE broadcast_recipients SET status='failed', error=? "
                "WHERE broadcast_id=? AND user_id=?",
                (err, broadcast_id, uid))
            c2.execute(
                "UPDATE broadcasts SET failed_count=failed_count+1 WHERE id=?",
                (broadcast_id,))
            c2.commit()
            c2.close()
            failed += 1
        await asyncio.sleep(rate_limit)

    # Mark complete
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE broadcasts SET status='completed', completed_at=datetime('now') "
        "WHERE id=?", (broadcast_id,))
    conn.commit()
    conn.close()
    return {'sent': sent, 'failed': failed}
