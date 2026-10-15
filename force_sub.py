"""Forced channel subscription system."""
import sqlite3
import re


def get_active_channels(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM force_channels WHERE active=1").fetchall()
    except Exception:
        rows = []
    conn.close()
    return [dict(r) for r in rows]


def parse_channel_input(text):
    """Parse channel ID, @username, or t.me link."""
    text = text.strip()
    # Numeric ID
    if re.match(r'^-?\d+$', text):
        return {'channel_id': text, 'username': ''}
    # @username
    m = re.match(r'^@([A-Za-z0-9_]{5,})$', text)
    if m:
        return {'channel_id': '', 'username': '@' + m.group(1)}
    # t.me link
    m = re.match(r'^(?:https?://)?t\.me/([A-Za-z0-9_]{5,})(?:/.*)?$', text)
    if m:
        return {'channel_id': '', 'username': '@' + m.group(1)}
    return None


async def check_membership(bot, db_path, user_id):
    """Check if user is subscribed to all active channels.
    Returns (all_ok, missing_channels)."""
    channels = get_active_channels(db_path)
    if not channels:
        return True, []
    missing = []
    for ch in channels:
        chat_id = ch['channel_id'] or ch['username']
        if not chat_id:
            continue
        try:
            member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
            if member.status in ('left', 'kicked', 'restricted'):
                missing.append(ch)
        except Exception:
            # Can't check = treat as missing (need admin to fix)
            missing.append(ch)
    return len(missing) == 0, missing


def add_channel(db_path, channel_id, username, title='', invite_link=''):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO force_channels (channel_id, username, title, invite_link) "
            "VALUES (?,?,?,?)", (channel_id, username, title, invite_link))
        conn.commit()
        return True, 'added'
    except sqlite3.IntegrityError:
        return False, 'already_exists'
    finally:
        conn.close()
