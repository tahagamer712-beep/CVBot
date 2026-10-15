"""SQLite storage for CV bot — orders + settings + keys + audit + users + edits + memory."""
import json
import os
import sqlite3
import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, 'cvbot.db')

SCHEMA_ORDERS = """
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    username TEXT,
    full_name TEXT,
    phone TEXT,
    email TEXT,
    address TEXT,
    job_title TEXT,
    summary TEXT,
    experience TEXT,
    education TEXT,
    certs TEXT,
    skills TEXT,
    languages TEXT,
    lang TEXT,
    design TEXT,
    status TEXT,
    proof_file_id TEXT,
    free_edit_used INTEGER DEFAULT 0,
    created_at TEXT,
    updated_at TEXT
);
"""

# New columns added on existing orders table (ALTER, safe if already present)
ORDERS_NEW_COLS = [
    ('service_type', 'TEXT'),
    ('field', 'TEXT'),
    ('market', 'TEXT'),
    ('level', 'TEXT'),
    ('template_id', 'TEXT'),
    ('photo_path', 'TEXT'),
    ('payment_status', 'TEXT DEFAULT "unpaid"'),
    ('approved_by', 'INTEGER'),
    ('approved_at', 'TEXT'),
    ('reject_reason', 'TEXT'),
    ('original_data', 'TEXT'),
    ('quality_status', 'TEXT'),
    ('draft_step', 'TEXT'),
    ('edits_free_left', 'INTEGER DEFAULT 2'),
    ('edits_paid_left', 'INTEGER DEFAULT 0'),
    ('reupload_count', 'INTEGER DEFAULT 0'),
    ('rejected_at', 'TEXT'),
]

SCHEMA_EXTRA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_name TEXT NOT NULL,
    encrypted_key TEXT NOT NULL,
    key_suffix TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER,
    action TEXT,
    detail TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_seen TEXT,
    last_seen TEXT,
    ui_lang TEXT DEFAULT 'ar'
);
CREATE TABLE IF NOT EXISTS edit_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT,
    user_id INTEGER,
    kind TEXT,
    field TEXT,
    old_value TEXT,
    new_value TEXT,
    charged INTEGER DEFAULT 0,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS professional_memory (
    user_id INTEGER PRIMARY KEY,
    data TEXT,
    consented_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS templates (
    id TEXT PRIMARY KEY,
    name_ar TEXT,
    name_en TEXT,
    description_ar TEXT,
    best_for_ar TEXT,
    languages TEXT,
    ats_compatible INTEGER,
    ready INTEGER DEFAULT 0,
    sort_order INTEGER DEFAULT 0,
    design_key TEXT
);
"""


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def _now():
    return datetime.datetime.now().isoformat(timespec='seconds')


def init():
    with _conn() as c:
        c.execute(SCHEMA_ORDERS)
        c.executescript(SCHEMA_EXTRA)
        cols = {r[1] for r in c.execute('PRAGMA table_info(orders)').fetchall()}
        for name, decl in ORDERS_NEW_COLS:
            if name not in cols:
                c.execute(f'ALTER TABLE orders ADD COLUMN {name} {decl}')


# ---------- orders ----------
def create_order(order_id, user_id, username):
    with _conn() as c:
        c.execute(
            'INSERT INTO orders (order_id, user_id, username, status, payment_status,'
            ' created_at, updated_at) VALUES (?,?,?,?,?,?,?)',
            (order_id, user_id, username, 'collecting', 'unpaid', _now(), _now()))


def update(order_id, **fields):
    fields['updated_at'] = _now()
    sets = ', '.join(f'{k}=?' for k in fields)
    with _conn() as c:
        c.execute(f'UPDATE orders SET {sets} WHERE order_id=?',
                  (*fields.values(), order_id))


def cas_update(order_id, expect, **fields):
    """Atomic compare-and-set: UPDATE only if current columns match `expect`.

    Returns True iff exactly one row was changed (i.e. we won the race).
    Use for payment/state transitions to make double-clicks and Telegram
    callback redelivery idempotent.
    """
    fields['updated_at'] = _now()
    sets = ', '.join(f'{k}=?' for k in fields)
    where = ' AND '.join(f'{k}=?' for k in expect)
    with _conn() as c:
        cur = c.execute(
            f'UPDATE orders SET {sets} WHERE order_id=? AND {where}',
            (*fields.values(), order_id, *expect.values()))
        return cur.rowcount == 1


def cas_payment_review(order_id, proof_file_id):
    """Atomically move unpaid/awaiting_receipt -> under_review (first receipt)."""
    with _conn() as c:
        cur = c.execute(
            "UPDATE orders SET proof_file_id=?, payment_status='under_review',"
            " status='payment_review', updated_at=? WHERE order_id=?"
            " AND payment_status IN ('unpaid','awaiting_receipt')",
            (proof_file_id, _now(), order_id))
        return cur.rowcount == 1


def cas_reupload_review(order_id, proof_file_id, attempt):
    """Atomically move rejected -> under_review for a re-uploaded receipt."""
    with _conn() as c:
        cur = c.execute(
            "UPDATE orders SET proof_file_id=?, payment_status='under_review',"
            " status='payment_review', reupload_count=?, updated_at=?"
            " WHERE order_id=? AND payment_status='rejected'",
            (proof_file_id, attempt, _now(), order_id))
        return cur.rowcount == 1


def cas_regen_start(order_id):
    """Atomically claim a paid-but-failed order for regeneration."""
    with _conn() as c:
        cur = c.execute(
            "UPDATE orders SET status='regenerating', updated_at=?"
            " WHERE order_id=? AND status='quality_failed'"
            " AND payment_status='approved'",
            (_now(), order_id))
        return cur.rowcount == 1


def reset_stuck_generating():
    """Startup recovery: orders left in 'regenerating' by a crash/restart
    go back to 'quality_failed' so the admin regen button works again."""
    with _conn() as c:
        cur = c.execute(
            "UPDATE orders SET status='quality_failed', updated_at=?"
            " WHERE status='regenerating'", (_now(),))
        return cur.rowcount


def stuck_orders():
    """Orders needing admin attention: payment_review older than 24h,
    any quality_failed, generating older than 1h."""
    now = datetime.datetime.now()
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM orders WHERE status IN"
            " ('payment_review','quality_failed','generating')"
            " ORDER BY updated_at ASC").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            upd = datetime.datetime.fromisoformat(d.get('updated_at') or '')
            age_h = (now - upd).total_seconds() / 3600
        except Exception:
            age_h = 9999.0
        st = d.get('status')
        if st == 'payment_review' and age_h > 24:
            out.append((d, f'مراجعة دفع عالقة ({age_h:.0f}h)'))
        elif st == 'quality_failed':
            out.append((d, 'فشل التوليد'))
        elif st == 'generating' and age_h > 1:
            out.append((d, f'توليد عالق ({age_h:.0f}h)'))
    return out


def get(order_id):
    with _conn() as c:
        row = c.execute('SELECT * FROM orders WHERE order_id=?', (order_id,)).fetchone()
        return dict(row) if row else None


def set_json(order_id, key, value):
    update(order_id, **{key: json.dumps(value, ensure_ascii=False)})


def get_data(order_id):
    o = get(order_id)
    if not o:
        return None
    d = dict(o)
    for k in ('experience', 'certs', 'skills', 'languages', 'original_data'):
        try:
            d[k] = json.loads(d[k]) if d[k] else ([] if k != 'original_data' else None)
        except Exception:
            d[k] = [] if k != 'original_data' else None
    return d


def user_orders(user_id, limit=10):
    with _conn() as c:
        rows = c.execute(
            'SELECT * FROM orders WHERE user_id=? ORDER BY created_at DESC LIMIT ?',
            (user_id, limit)).fetchall()
        return [dict(r) for r in rows]


def user_draft(user_id):
    """Latest unfinished order for resume."""
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM orders WHERE user_id=? AND status NOT IN"
            " ('delivered','cancelled','closed') ORDER BY updated_at DESC LIMIT 1",
            (user_id,)).fetchone()
        return dict(row) if row else None


def pending_payments():
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM orders WHERE payment_status='under_review'"
            ' ORDER BY updated_at ASC').fetchall()
        return [dict(r) for r in rows]


def stats():
    with _conn() as c:
        s = {}
        s['orders_total'] = c.execute('SELECT COUNT(*) FROM orders').fetchone()[0]
        s['delivered'] = c.execute(
            "SELECT COUNT(*) FROM orders WHERE status='delivered'").fetchone()[0]
        s['pending_pay'] = c.execute(
            "SELECT COUNT(*) FROM orders WHERE payment_status='under_review'").fetchone()[0]
        s['users'] = c.execute('SELECT COUNT(*) FROM users').fetchone()[0]
        return s


# ---------- settings ----------
def get_setting(key, default=None):
    with _conn() as c:
        row = c.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return row['value'] if row else default


def set_setting(key, value):
    with _conn() as c:
        c.execute('INSERT OR REPLACE INTO settings (key, value, updated_at)'
                  ' VALUES (?,?,?)', (key, value, _now()))


# ---------- api keys ----------
def add_api_key(provider_name, encrypted_key, key_suffix):
    with _conn() as c:
        c.execute('UPDATE api_keys SET is_active=0 WHERE provider_name=?',
                  (provider_name,))
        c.execute(
            'INSERT INTO api_keys (provider_name, encrypted_key, key_suffix,'
            ' is_active, created_at) VALUES (?,?,?,?,?)',
            (provider_name, encrypted_key, key_suffix, 1, _now()))


def get_active_key(provider_name):
    with _conn() as c:
        row = c.execute(
            'SELECT * FROM api_keys WHERE provider_name=? AND is_active=1'
            ' ORDER BY id DESC LIMIT 1', (provider_name,)).fetchone()
        return dict(row) if row else None


# ---------- audit ----------
def audit(admin_id, action, detail=''):
    with _conn() as c:
        c.execute(
            'INSERT INTO audit_log (admin_id, action, detail, created_at)'
            ' VALUES (?,?,?,?)', (admin_id, action, detail[:500], _now()))


def recent_audit(limit=20):
    with _conn() as c:
        rows = c.execute(
            'SELECT * FROM audit_log ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
        return [dict(r) for r in rows]


# ---------- users ----------
def upsert_user(user_id, username):
    with _conn() as c:
        row = c.execute('SELECT user_id FROM users WHERE user_id=?',
                        (user_id,)).fetchone()
        if row:
            c.execute('UPDATE users SET last_seen=?, username=? WHERE user_id=?',
                      (_now(), username, user_id))
        else:
            c.execute(
                'INSERT INTO users (user_id, username, first_seen, last_seen)'
                ' VALUES (?,?,?,?)', (user_id, username, _now(), _now()))


# ---------- edit ledger ----------
def log_edit(order_id, user_id, kind, field, old_value, new_value, charged):
    with _conn() as c:
        c.execute(
            'INSERT INTO edit_ledger (order_id, user_id, kind, field, old_value,'
            ' new_value, charged, created_at) VALUES (?,?,?,?,?,?,?,?)',
            (order_id, user_id, kind, field,
             (old_value or '')[:500], (new_value or '')[:500],
             1 if charged else 0, _now()))


def edit_history(order_id):
    with _conn() as c:
        rows = c.execute(
            'SELECT * FROM edit_ledger WHERE order_id=? ORDER BY id DESC',
            (order_id,)).fetchall()
        return [dict(r) for r in rows]


# ---------- professional memory ----------
def memory_get(user_id):
    with _conn() as c:
        row = c.execute('SELECT * FROM professional_memory WHERE user_id=?',
                        (user_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d['data'] = json.loads(d['data']) if d['data'] else {}
        except Exception:
            d['data'] = {}
        return d


def memory_save(user_id, data):
    with _conn() as c:
        row = c.execute('SELECT consented_at FROM professional_memory WHERE user_id=?',
                        (user_id,)).fetchone()
        consented = row['consented_at'] if row else _now()
        c.execute(
            'INSERT OR REPLACE INTO professional_memory'
            ' (user_id, data, consented_at, updated_at) VALUES (?,?,?,?)',
            (user_id, json.dumps(data, ensure_ascii=False), consented, _now()))


def memory_delete(user_id):
    with _conn() as c:
        c.execute('DELETE FROM professional_memory WHERE user_id=?', (user_id,))


# ---------- templates ----------
def upsert_template(t):
    with _conn() as c:
        c.execute(
            'INSERT OR REPLACE INTO templates (id, name_ar, name_en, description_ar,'
            ' best_for_ar, languages, ats_compatible, ready, sort_order, design_key)'
            ' VALUES (?,?,?,?,?,?,?,?,?,?)',
            (t['id'], t.get('name_ar'), t.get('name_en'), t.get('description_ar'),
             t.get('best_for_ar'), t.get('languages', 'ar,en'),
             t.get('ats_compatible', 0), t.get('ready', 0),
             t.get('sort_order', 0), t.get('design_key')))


def ready_templates(lang='ar'):
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM templates WHERE ready=1 AND languages LIKE ?"
            ' ORDER BY sort_order', (f'%{lang}%',)).fetchall()
        return [dict(r) for r in rows]


def all_templates():
    with _conn() as c:
        rows = c.execute('SELECT * FROM templates ORDER BY sort_order').fetchall()
        return [dict(r) for r in rows]


def set_template_ready(tid, ready):
    with _conn() as c:
        c.execute('UPDATE templates SET ready=? WHERE id=?', (1 if ready else 0, tid))
