"""CV Admin Center — comprehensive admin management from Telegram.

All stats from real DB. No fake numbers. All buttons have real handlers.
"""
import sqlite3
import datetime


def _conn(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def get_dashboard_stats(db_path):
    """Real stats from DB. Returns dict."""
    conn = _conn(db_path)
    s = {}
    try:
        s['orders_total'] = conn.execute(
            "SELECT COUNT(*) FROM orders").fetchone()[0]
        s['orders_new'] = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE status IN "
            "('collecting','template','preview')").fetchone()[0]
        s['orders_processing'] = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE status IN "
            "('generating','under_review')").fetchone()[0]
        s['orders_stuck'] = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE status IN "
            "('quality_failed','regenerating')").fetchone()[0]
        s['orders_delivered'] = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE status='delivered'").fetchone()[0]
        s['pay_pending'] = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE payment_status='under_review'"
            ).fetchone()[0]
        s['pay_approved'] = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE payment_status='approved'"
            ).fetchone()[0]
        # Revenue: only approved payments (price fixed at 5000 IQD)
        # Free referral orders excluded from revenue
        row = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE payment_status='approved' "
            "AND (is_free_reward IS NULL OR is_free_reward=0)").fetchone()
        s['paid_orders'] = row[0] or 0
        s['revenue_iqd'] = s['paid_orders'] * 5000
        # Costs
        try:
            s['costs_iqd'] = conn.execute(
                "SELECT COALESCE(SUM(amount_iqd),0) FROM costs").fetchone()[0] or 0
        except Exception:
            s['costs_iqd'] = 0
        s['net_profit_iqd'] = s['revenue_iqd'] - s['costs_iqd']
        s['users_total'] = conn.execute(
            "SELECT COUNT(*) FROM users").fetchone()[0]
        # New users (last 7 days)
        try:
            s['users_new'] = conn.execute(
                "SELECT COUNT(*) FROM users WHERE created_at >= "
                "datetime('now','-7 days')").fetchone()[0]
        except Exception:
            s['users_new'] = 0
        # Ratings
        try:
            r = conn.execute(
                "SELECT AVG(rating), COUNT(*) FROM ratings").fetchone()
            s['rating_avg'] = round(r[0], 1) if r[0] else None
            s['rating_count'] = r[1] or 0
        except Exception:
            s['rating_avg'] = None
            s['rating_count'] = 0
        # Referrals
        try:
            s['referrals_total'] = conn.execute(
                "SELECT COUNT(*) FROM referrals").fetchone()[0]
        except Exception:
            s['referrals_total'] = 0
        # Channels
        try:
            s['channels_active'] = conn.execute(
                "SELECT COUNT(*) FROM force_channels WHERE active=1"
                ).fetchone()[0]
        except Exception:
            s['channels_active'] = 0
        # Needs attention
        s['needs_attention'] = (s['pay_pending'] + s['orders_stuck'])
    except Exception as e:
        s['error'] = str(e)
    conn.close()
    return s


def format_dashboard(s):
    """Format dashboard text in Arabic."""
    if s.get('error'):
        return '⚠️ خطأ في جلب البيانات: ' + s['error']
    lines = [
        '🏢 *CV ADMIN CENTER*',
        'مركز إدارة بوت السير الذاتية',
        '',
        '📊 *الإحصائيات*',
        f"📦 إجمالي الطلبات: {s['orders_total']}",
        f"🆕 جديدة: {s['orders_new']} | ⏳ قيد المعالجة: {s['orders_processing']}",
        f"⚠️ عالقة: {s['orders_stuck']} | ✅ مسلّمة: {s['orders_delivered']}",
        '',
        f"💳 مدفوعات معلقة: {s['pay_pending']} | ✅ مقبولة: {s['pay_approved']}",
        f"💰 الإيرادات المؤكدة: {s['revenue_iqd']:,} د.ع",
        f"📈 صافي الربح: {s.get('net_profit_iqd', 0):,} د.ع",
        '',
        f"👥 المستخدمون: {s['users_total']} (جدد: {s['users_new']})",
    ]
    if s['rating_avg'] is not None:
        lines.append(f"⭐ التقييم: {s['rating_avg']}/10 ({s['rating_count']})")
    else:
        lines.append('⭐ التقييم: لا توجد تقييمات بعد')
    lines.append(f"🎁 الدعوات: {s['referrals_total']} | 📢 القنوات: {s['channels_active']}")
    if s['needs_attention'] > 0:
        lines += ['', f"🚨 *يحتاج تدخلك الآن: {s['needs_attention']}*"]
    return '\n'.join(lines)


# --- Database migrations for new features ---
def migrate_admin_center(db_path):
    """Add tables for ratings, broadcasts, channels, costs, rewards."""
    conn = _conn(db_path)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS ratings (
        order_id TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 10),
        comment TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS broadcasts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_id INTEGER NOT NULL,
        content_type TEXT NOT NULL,
        content_ref TEXT NOT NULL,
        caption TEXT DEFAULT '',
        status TEXT DEFAULT 'draft',
        target_count INTEGER DEFAULT 0,
        sent_count INTEGER DEFAULT 0,
        failed_count INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now')),
        completed_at TEXT
    );
    CREATE TABLE IF NOT EXISTS broadcast_recipients (
        broadcast_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        status TEXT DEFAULT 'pending',
        error TEXT DEFAULT '',
        PRIMARY KEY (broadcast_id, user_id)
    );
    CREATE TABLE IF NOT EXISTS force_channels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        channel_id TEXT NOT NULL UNIQUE,
        username TEXT DEFAULT '',
        title TEXT DEFAULT '',
        invite_link TEXT DEFAULT '',
        active INTEGER DEFAULT 1,
        added_at TEXT DEFAULT (datetime('now')),
        last_check TEXT,
        last_check_ok INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS costs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT NOT NULL,
        amount_iqd INTEGER NOT NULL,
        description TEXT DEFAULT '',
        recorded_by INTEGER NOT NULL,
        recorded_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS rewards (
        user_id INTEGER PRIMARY KEY,
        referrals_count INTEGER DEFAULT 0,
        reward_status TEXT DEFAULT 'locked',
        reward_order_id TEXT DEFAULT '',
        unlocked_at TEXT,
        used_at TEXT
    );
    CREATE TABLE IF NOT EXISTS referral_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        referrer_id INTEGER NOT NULL,
        referred_id INTEGER NOT NULL UNIQUE,
        created_at TEXT DEFAULT (datetime('now'))
    );
    """)
    conn.commit()
    conn.close()
    return True
