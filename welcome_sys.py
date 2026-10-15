"""Welcome message management."""
import sqlite3

DEFAULT_WELCOME = """أهلًا بيك في بوت السيرة الذاتية الاحترافية 🎓📄

نساعدك تنشئ سيرة ذاتية منظمة بصيغة PDF + Word، بتصميم احترافي مناسب لأنظمة التوظيف.

💰 السعر: 5,000 دينار عراقي فقط للسيرة الواحدة.

📝 خطوات إنشاء سيرتك:
1️⃣ اضغط «إنشاء سيرة جديدة» وأدخل معلوماتك.
2️⃣ اختر القالب واللغة (عربي / إنجليزي).
3️⃣ ادفع 5,000 د.ع عبر التحويل اليدوي.
4️⃣ أرسل صورة إيصال التحويل المكتمل والواضح.
5️⃣ بعد مراجعة الإيصال والموافقة، تستلم ملفاتك.

⚠️ ملاحظة: السيرة الاحترافية تحسّن فرصك لكنها لا تضمن التوظيف.

اختر من الأزرار أدناه للبدء 👇"""


def get_welcome(db_path):
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT value FROM settings WHERE key='welcome_message'"
            ).fetchone()
        msg = row[0] if row else DEFAULT_WELCOME
    except Exception:
        msg = DEFAULT_WELCOME
    conn.close()
    return msg


def set_welcome(db_path, message, admin_id):
    """Save welcome message. Returns (ok, error)."""
    if not message or len(message.strip()) < 20:
        return False, 'too_short'
    if len(message) > 4000:
        return False, 'too_long'
    # Validate variables
    allowed_vars = ['{user_name}', '{bot_name}']
    import re
    vars_used = re.findall(r'\{[^}]+\}', message)
    for v in vars_used:
        if v not in allowed_vars:
            return False, f'invalid_var:{v}'
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO settings (key, value) VALUES ('welcome_message', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (message,))
    conn.commit()
    conn.close()
    return True, 'saved'
