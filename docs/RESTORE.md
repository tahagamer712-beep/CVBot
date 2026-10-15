# استعادة بوت السيفيات من نسخة احتياطية (RESTORE)

> بدون أسرار: هذه الوثيقة لا تحتوي أي توكنات أو مفاتيح. الأسرار تعيش فقط في
> `~/bots/cvbot/.env` (صلاحيات 600) ولا تُنسخ كنص في أي مكان آخر.

## ما الذي يُنسخ احتياطيًا؟

| المكوّن | المسار على الهاتف | ملاحظات |
|---|---|---|
| قاعدة البيانات | `~/bots/cvbot/cvbot.db` | عبر `sqlite3 ... ".backup ..."` (نسخة متسقة حتى والبوت شغّال) |
| ملفات الطلبات | `~/bots/cvbot/orders/` | صور، PDF، DOCX، معاينات |
| قائمة ملفات الإعداد | أسماء فقط (`.env`، `*.py`، `*.sh`، `*.txt`) | **لا يُنسخ محتوى `.env` نفسه** — يُعاد إنشاؤه يدويًا |

الكود المصدري محفوظ في GitHub ولا يدخل النسخة الاحتياطية.

## أخذ نسخة احتياطية (نسخ/لصق)

```bash
H=/data/data/com.termux/files/home
TS=$(date +%Y%m%d-%H%M)
mkdir -p ~/tmp/cvbot-backup-$TS
sqlite3 $H/bots/cvbot/cvbot.db ".backup '$H/tmp/cvbot-backup-$TS/cvbot.db'"
cp -a $H/bots/cvbot/orders $H/tmp/cvbot-backup-$TS/orders
cd $H/bots/cvbot && ls -1 *.py *.txt *.sh .env .gitignore 2>/dev/null | sort \
  > $H/tmp/cvbot-backup-$TS/config-files.txt
du -sh ~/tmp/cvbot-backup-$TS
```

## الاستعادة الكاملة (نسخ/لصق)

> نفّذها والبوت **متوقف**. لا توقف جلسة tmux المسماة `bots` أبدًا —
> أوقف `cvbot` فقط من داخلها (Ctrl-C في نافذة الجلسة) أو عبر مشرفها.

```bash
H=/data/data/com.termux/files/home
BK=~/tmp/cvbot-backup-YYYYMMDD-HHMM   # ← عدّل التاريخ هنا

# 1) تحقق من سلامة النسخة قبل اللمس
sqlite3 $BK/cvbot.db "PRAGMA integrity_check;"   # يجب أن تطبع: ok

# 2) احفظ الحالة الحالية جانبًا (لا تحذف شيئًا)
mv $H/bots/cvbot/cvbot.db    $H/bots/cvbot/cvbot.db.before-restore
mv $H/bots/cvbot/orders      $H/bots/cvbot/orders.before-restore

# 3) انسخ النسخة إلى مكانها
cp $BK/cvbot.db $H/bots/cvbot/cvbot.db
cp -a $BK/orders $H/bots/cvbot/orders
chmod 600 $H/bots/cvbot/cvbot.db

# 4) تحقق بعد الاستعادة
sqlite3 $H/bots/cvbot/cvbot.db "PRAGMA integrity_check;"
sqlite3 $H/bots/cvbot/cvbot.db "SELECT COUNT(*) FROM orders; SELECT COUNT(*) FROM users;"

# 5) أعد تشغيل البوت من داخل جلسة tmux المسماة cvbot ثم احذف النسخ الجانبية
#    فقط بعد التأكد أن البوت يعمل ويستقبل:
#    rm $H/bots/cvbot/cvbot.db.before-restore
#    rm -rf $H/bots/cvbot/orders.before-restore
```

## استعادة `.env` (يدوي — لا يوجد في النسخة)

أعد إنشاء `~/bots/cvbot/.env` من مصدر الأسرار الموثوق (مدير كلمات المرور)،
ثم:

```bash
chmod 600 ~/bots/cvbot/.env
```

## آخر اختبار استعادة موثّق

- التاريخ: 2026-10-14 — النسخة: `~/tmp/cvbot-backup-20261014-1305`
- `PRAGMA integrity_check;` → `ok`
- عدّ الصفوف (حي مقابل مستعاد): orders 8=8، users 1=1، settings 2=2،
  api_keys 1=1، audit_log 7=7، edit_ledger 1=1، professional_memory 0=0،
  templates 12=12 — كلها متطابقة
- قائمة ملفات `orders/` متطابقة تمامًا (`diff` فارغ)

## اختبار استعادة 2026-10-14 (16:11) — نسخة 20261014-1610
- الحجم: 1.4MB — المكونات: cvbot.db + orders/ + كل ملفات .py + run_cvbot.sh + requirements.txt + docs/ + start-bots.boot (بدون .env — الأسرار مستبعدة)
- فحص السلامة على نسخة منفصلة: سليم (ok)
- عدّ الصفوف (حي مقابل مستعاد): orders 39=39، users 1=1 — متطابق
- مجلد orders/ متطابق تمامًا (لا فروقات)
- فحص الأسرار: رقم كي كارد 0 ظهور، مفاتيح API حقيقية 0 (سطر واحد في test_all.py مجرد assertion نصي)
- النسخة محلية على الهاتف فقط — لا نسخة خارج الهاتف بعد
