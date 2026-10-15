"""CV Bot — sells professional CVs (PDF + DOCX) for 5,000 IQD via Key Card.
Run: python bot.py   (token from .env)
"""
import logging
import os
import random
import re
import datetime
from dotenv import load_dotenv

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (Application, ApplicationHandlerStop, CallbackQueryHandler,
                          CommandHandler, ConversationHandler, MessageHandler,
                          ContextTypes, filters)

import db
from cvgen import generate_pdf, generate_docx, pdf_first_page_png, generate_preview
from coverletter import make_cover_letter
from utils.security import is_admin as check_admin, mask_key, decrypt_key, encrypt_key
from templates_registry import seed_templates, design_for_template
from ai.providers import OpenRouterProvider, fetch_openrouter_free_models
from ai.engine import WritingEngine, suggest_skills_list, skill_cap
import quality
import antifab
import features as feat
import photo as photomod

AI_PAGE_SIZE = 8

load_dotenv()
TOKEN = os.environ['BOT_TOKEN']
ADMIN_ID = int(os.environ.get('ADMIN_ID', '0'))
KEYCARD_NUMBER = os.environ.get('KEYCARD_NUMBER', '').strip()
PRICE = '5,000'
# receipt re-upload policy after rejection: max attempts within N days of rejection
REUPLOAD_MAX = 3
REUPLOAD_WINDOW_DAYS = 7
BASE = os.path.dirname(os.path.abspath(__file__))

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s')
# SECURITY: httpx/telegram log full URLs incl. bot token at INFO — silence them
for _n in ('httpx', 'telegram', 'telegram.ext'):
    logging.getLogger(_n).setLevel(logging.WARNING)
log = logging.getLogger('cvbot')


async def _guard_keycard(q, ctx):
    """Payment-config guard: True only when KEYCARD_NUMBER is set.

    On missing/empty config it never shows wrong payment instructions:
    the user gets a safe notice and the admin gets a clear alert.
    The number itself is never logged."""
    if KEYCARD_NUMBER and str(KEYCARD_NUMBER).strip():
        return True
    try:
        await q.message.reply_text(
            '\u26a0\ufe0f \u0639\u0630\u0631\u064b\u0627 \u2014 '
            '\u0627\u0644\u062f\u0641\u0639 \u063a\u064a\u0631 '
            '\u0645\u062a\u0627\u062d \u0645\u0624\u0642\u062a\u064b\u0627 '
            '\u0644\u0633\u0628\u0628 \u062a\u0642\u0646\u064a.\n'
            '\u062a\u0645 \u0625\u0634\u0639\u0627\u0631 '
            '\u0627\u0644\u0625\u062f\u0627\u0631\u0629\u061b')
    except Exception:
        pass
    try:
        await ctx.bot.send_message(
            chat_id=ADMIN_ID,
            text='\U0001f6a8 \u062a\u0646\u0628\u064a\u0647: '
                 'KEYCARD_NUMBER \u063a\u064a\u0631 \u0645\u0636\u0628\u0648\u0637 '
                 '\u0641\u064a .env \u2014 \u062a\u0639\u0644\u064a\u0645\u0627\u062a '
                 '\u0627\u0644\u062f\u0641\u0639 \u0645\u062a\u0648\u0642\u0641\u0629.')
    except Exception:
        pass
    log.error('payment blocked: KEYCARD_NUMBER missing or empty')
    return False


def _info_text(kind):
    """Load policy/FAQ markdown and convert to Telegram legacy Markdown."""
    fn = os.path.join(BASE, 'docs',
                      'POLICY-refund.md' if kind == 'policy' else 'FAQ.md')
    try:
        t = open(fn, encoding='utf-8').read()
    except Exception:
        return '\u26a0\ufe0f \u0627\u0644\u0645\u062d\u062a\u0648\u0649 \u063a\u064a\u0631 \u0645\u062a\u0627\u062d.'
    out = []
    for line in t.split('\n'):
        line = re.sub(r'^#{1,3}\s*', '', line)
        line = re.sub(r'^>\s*', '', line)
        line = line.replace('**', '*')
        out.append(line)
    text = '\n'.join(out).strip()
    return text[:4000] if len(text) > 4000 else text


async def info_cb(update, ctx):
    q = update.callback_query
    await q.answer()
    parts = q.data.split(':', 1)
    if len(parts) > 1 and parts[1] == 'home':
        await start(update, ctx)
        return
    text = _info_text(parts[1] if len(parts) > 1 else 'policy')
    kb = [[InlineKeyboardButton('\U0001f519 \u0627\u0644\u0642\u0627\u0626\u0645\u0629 \u0627\u0644\u0631\u0626\u064a\u0633\u064a\u0629',
                               callback_data='info:home')]]
    await q.message.reply_text(text, parse_mode='Markdown',
                               reply_markup=InlineKeyboardMarkup(kb))


async def policy_cmd(update, ctx):
    await update.message.reply_text(_info_text('policy'), parse_mode='Markdown')


async def faq_cmd(update, ctx):
    await update.message.reply_text(_info_text('faq'), parse_mode='Markdown')

# ---------- conversation states ----------
(LANG, NAME, PHONE, EMAIL, ADDRESS, JOB_TITLE, TARGET_JOB, SUMMARY,
 EXP_TITLE, EXP_COMPANY, EXP_PERIOD, EXP_DESC, EXP_MORE,
 EDUCATION, CERTS, SKILLS, LANGS_KNOWN, DESIGN,
 PREVIEW_OK, PROOF, EDIT_CHOICE, EDIT_VALUE,
 PHOTO_CHOICE, PHOTO_WAIT, ADMIN_MENU, ADMIN_AI_MODELS, ADMIN_AI_KEY,
 EDIT_KIND, SUMMARY_REVIEW) = range(29)
(INTV_JOB, INTV_TYPE, INTV_DIFF, INTV_ASK, INTV_FEEDBACK,
 IMPORT_WAIT, IMPORT_REVIEW,
 MEM_MENU, EXP_PICK) = range(28, 37)

def template_label(t, lang='ar'):
    name = t['name_ar'] if lang == 'ar' else t['name_en']
    desc = t.get('description_ar') or ''
    ats = ' ✅ATS' if t.get('ats_compatible') else ''
    return f'{name}{ats}\n{desc}'


def get_template(tid):
    for t in db.all_templates():
        if t['id'] == tid:
            return t
    return None
LANG_NAMES = {'ar': 'العربي', 'en': 'English', 'both': 'العربي + English'}


def new_order_id():
    return f"CV-{random.randint(100000, 999999)}"


def order_dir(order_id):
    d = os.path.join(BASE, 'orders', order_id)
    os.makedirs(d, exist_ok=True)
    return d


# ================= /start =================
def get_engine():
    """Build WritingEngine with OpenRouter LLM if key exists, else rule-based."""
    try:
        key_row = db.get_active_key('openrouter')
        if key_row:
            api_key = decrypt_key(key_row['encrypted_key'])
            provider = OpenRouterProvider(api_key)

            async def llm(system, user):
                return await provider.complete(system, user)

            return WritingEngine(llm=llm)
    except Exception:
        pass
    return WritingEngine(llm=None)

def get_builder():
    """Build AIBuilder with OpenRouter LLM if key exists, else rule-based."""
    from ai.cv_builder import AIBuilder
    try:
        key_row = db.get_active_key('openrouter')
        if key_row:
            api_key = decrypt_key(key_row['encrypted_key'])
            provider = OpenRouterProvider(api_key)

            async def llm(system, user):
                return await provider.complete(system, user, max_tokens=1200)

            return AIBuilder(llm=llm)
    except Exception:
        pass
    return AIBuilder(llm=None)


async def _ai_enhance_order(order_id):
    """Run AI content pipeline on order data before preview/build.
    Returns report list. Stores enhanced data + keeps original."""
    from ai.cv_builder import AIBuilder
    d = db.get_data(order_id)
    lang = d.get('lang') or 'ar'
    if lang == 'both':
        lang = 'ar'
    builder = get_builder()
    enhanced, report = await builder.build_full_cv(d, lang)
    # persist enhanced fields (keep original_data snapshot intact)
    import json as _json
    updates = {}
    for k in ('summary', 'experience', 'skills', 'achievements',
              'skills_ai_suggestion', '_review_notes'):
        if k in enhanced:
            v = enhanced[k]
            # Serialize lists/dicts to JSON for SQLite TEXT columns
            if isinstance(v, (list, dict)):
                v = _json.dumps(v, ensure_ascii=False)
            updates[k] = v
    # merge AI skill suggestions into skills if user gave few
    cur_skills = d.get('skills') or []
    if isinstance(cur_skills, str):
        cur_skills = [s.strip() for s in cur_skills.split('\n') if s.strip()]
    if len(cur_skills) < 4 and enhanced.get('skills_ai_suggestion'):
        updates['skills_ai_note'] = enhanced['skills_ai_suggestion']
    if updates:
        db.update(order_id, **updates)
    # log report
    try:
        db.update(order_id, ai_build_report='\n'.join(report))
    except Exception:
        pass
    return report


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.upsert_user(user.id, user.username or '')
    # Forced subscription check (skip for admin)
    if not check_admin(user.id, ADMIN_ID):
        import force_sub
        ok, missing = await force_sub.check_membership(
            ctx.bot, db.DB_PATH, user.id)
        if not ok and missing:
            kb_sub = []
            for ch in missing:
                link = ch.get('invite_link') or ch.get('username') or ''
                if link:
                    if not link.startswith('http'):
                        link = 'https://t.me/' + link.lstrip('@')
                    kb_sub.append([InlineKeyboardButton(
                        f"📢 اشترك في {ch.get('title') or ch.get('username')}",
                        url=link)])
            kb_sub.append([InlineKeyboardButton(
                '✅ تحقّق من الاشتراك', callback_data='sub:check')])
            await update.message.reply_text(
                '📢 *اشترك في القنوات التالية لاستخدام البوت:*\n\n'
                'بعد الاشتراك اضغط «تحقّق من الاشتراك».',
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(kb_sub))
            return
    # a fresh /start cancels any pending receipt re-upload/clearer intent, so a
    # later photo in a new order can never be swallowed by the photo router
    ctx.user_data.pop('awaiting_receipt', None)
    # referral deep-link: /start ref_12345
    try:
        if ctx.args and ctx.args[0].startswith('ref_'):
            referrer = ctx.args[0][4:]
            if feat.track_referral(user.id, referrer):
                # Check if referrer unlocked reward
                import referral_sys
                if referral_sys.check_and_unlock_reward(
                        db.DB_PATH, int(referrer)):
                    try:
                        await ctx.bot.send_message(
                            chat_id=int(referrer),
                            text='🎉 *مبروك!* وصلت لـ 10 دعوات!\n'
                                 'سيرتك المجانية متاحة الآن. 🎁',
                            parse_mode='Markdown')
                    except Exception:
                        pass
    except Exception:
        pass
    kb = [[InlineKeyboardButton('📄 إنشاء سيفي جديد', callback_data='new')],
          [InlineKeyboardButton('📄 تطوير سيفي قديم', callback_data='import:old')],
          [InlineKeyboardButton('📋 طلباتي', callback_data='myorders')],
          [InlineKeyboardButton('🎁 ادعُ أصدقاءك واحصل على سيرة مجانية',
                                callback_data='ref:dashboard')],
          [InlineKeyboardButton('📜 سياسة الدفع والاسترجاع', callback_data='info:policy'),
           InlineKeyboardButton('❓ الأسئلة الشائعة', callback_data='info:faq')],
          [InlineKeyboardButton('🎤 التدريب للمقابلات', callback_data='intv:start')],
          [InlineKeyboardButton('👔 ملفي المهني', callback_data='mem:open'),
           InlineKeyboardButton('📤 مشاركة البوت', callback_data='share:open')]]
    # draft resume
    draft = db.user_draft(user.id)
    if draft and draft.get('status') in ('collecting', 'template', 'preview'):
        kb.insert(0, [InlineKeyboardButton(
            f"▶️ إكمال المسودة ({draft['order_id']})",
            callback_data=f"resume:{draft['order_id']}")])
    # (admin panel removed from user UI per spec — admin uses /admin)
    # Welcome message from DB (admin-editable), fallback to default
    try:
        import welcome_sys
        _welcome = welcome_sys.get_welcome(db.DB_PATH)
        # Replace variables
        _welcome = _welcome.replace('{user_name}',
                                    user.first_name or '')
        try:
            _me = await ctx.bot.get_me()
            _welcome = _welcome.replace('{bot_name}', _me.first_name or '')
        except Exception:
            pass
        text = _welcome
    except Exception:
        text = (
            '👋 أهلًا بيك ببوت *السيفي الاحترافي*\n\n'
            'أسويلك سيفي احترافي كامل بصيغة *PDF + Word* قابل للتعديل،\n'
            f'بسعر ثابت: *{PRICE} دينار عراقي* فقط.\n\n'
            '✅ قوالب مصممة لتكون صديقة لأنظمة التوظيف\n'
            '✅ عربي / إنكليزي / الاثنين\n'
            '✅ خطاب تقديم مجاني\n'
            '✅ أول تعديلين مجانيين\n\n'
            'اضغط الزر وابدأ 👇'
        )
    _is_admin = check_admin(user.id, ADMIN_ID)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(
            text, parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update.message.reply_text(text, parse_mode='Markdown',
                                        reply_markup=InlineKeyboardMarkup(kb))
    # Admin gets admin panel as SEPARATE message (spec)
    if _is_admin and update.message:
        try:
            import admin_center
            s = admin_center.get_dashboard_stats(db.DB_PATH)
            atext = admin_center.format_dashboard(s)
            await update.message.reply_text(atext, parse_mode='Markdown',
                                            reply_markup=_admin_kb())
        except Exception:
            pass
    return LANG


async def my_orders(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user_id = q.from_user.id
    orders = db.user_orders(user_id, limit=10)
    if not orders:
        await q.message.reply_text('📋 لا توجد طلبات بعد.\nاضغط 📄 إنشاء سيفي جديد للبدء.')
        return
    for o in orders:
        oid = o['order_id']
        st = o.get('status', '')
        pay = o.get('payment_status', '')
        st_ar = {'collecting': 'قيد الإنشاء', 'template': 'اختيار القالب',
                 'preview': 'معاينة', 'awaiting_payment': 'بانتظار الدفع',
                 'payment_review': 'مراجعة الدفع', 'generating': 'قيد التوليد',
                 'quality_check': 'فحص الجودة', 'quality_failed': 'فشل التوليد',
                 'regenerating': 'إعادة توليد', 'ready': 'جاهز',
                 'delivered': 'تم التسليم', 'rejected': 'مرفوض',
                 'closed': 'مغلق', 'cancelled': 'ملغى'}.get(st, st)
        pay_ar = {'unpaid': 'غير مدفوع', 'under_review': 'قيد المراجعة',
                  'awaiting_receipt': 'بانتظار الإيصال', 'approved': 'معتمد',
                  'rejected': 'مرفوض'}.get(pay, pay)
        kb = []
        if st == 'delivered':
            kb = [[InlineKeyboardButton('✐️ طلب تعديل', callback_data=f'edit:{oid}')],
                  [InlineKeyboardButton('🔧 الإبلاغ عن خطأ بالنظام', callback_data=f'syserr:{oid}')]]
        elif st in ('collecting', 'template', 'preview'):
            kb = [[InlineKeyboardButton('▶️ إكمال', callback_data=f'resume:{oid}')]]
        elif st == 'rejected':
            kb = [[InlineKeyboardButton('🔄 إعادة رفع الإيصال', callback_data=f'reup:{oid}')]]
        await q.message.reply_text(
            f'📋 `{oid}`\n📅 {o.get("created_at", "")[:10]} | 📌 {st_ar}\n💳 الدفع: {pay_ar}',
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(kb) if kb else None)


async def pick_lang(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == 'adm:open':
        await admin_entry(update, ctx)
        return ConversationHandler.END
    if q.data.startswith('resume:'):
        order_id = q.data.split(':')[1]
        d = db.get(order_id)
        if not d or d['user_id'] != q.from_user.id:
            await q.answer('المسودة غير موجودة.', show_alert=True)
            return LANG
        ctx.user_data['order_id'] = order_id
        ctx.user_data['exps'] = (db.get_data(order_id).get('experience') or [])
        await q.message.reply_text(
            f'▶️ نكمل من وين وكفت — الطلب `{order_id}`\n\n'
            '📝 اكتب اسمك الكامل (أو أرسل /cancel للبدء من جديد)',
            parse_mode='Markdown')
        return NAME
    if q.data == 'new':
        kb = [
            [InlineKeyboardButton('🇮🇶 عربي', callback_data='lang:ar')],
            [InlineKeyboardButton('🇬🇧 English', callback_data='lang:en')],
            [InlineKeyboardButton('🌍 الاثنين معًا', callback_data='lang:both')],
        ]
        await q.message.reply_text('اختر لغة السيفي:',
                                   reply_markup=InlineKeyboardMarkup(kb))
        return LANG
    # lang:xx
    lang = q.data.split(':')[1]
    order_id = new_order_id()
    db.create_order(order_id, q.from_user.id, q.from_user.username or '')
    db.update(order_id, lang=lang)
    ctx.user_data['order_id'] = order_id
    ctx.user_data['exps'] = []
    await q.message.reply_text(
        f'✅ رقم طلبك: `{order_id}`\nاللغة: {LANG_NAMES[lang]}\n\n'
        '📝 *الخطوة 1:* اكتب اسمك الكامل',
        parse_mode='Markdown')
    return NAME


# ================= data collection =================
async def got_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db.update(ctx.user_data['order_id'], full_name=update.message.text.strip())
    await update.message.reply_text('📝 *الخطوة 2:* رقم هاتفك',
                                    parse_mode='Markdown')
    return PHONE


async def got_phone(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db.update(ctx.user_data['order_id'], phone=update.message.text.strip())
    kb = [[InlineKeyboardButton('⏭ تخطي', callback_data='skip:email')]]
    await update.message.reply_text(
        '📝 *الخطوة 3:* بريدك الإلكتروني (أو تخطي)',
        parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    return EMAIL


async def got_email(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        email = ''
    else:
        email = update.message.text.strip()
        if '@' not in email:
            await update.message.reply_text('⚠️ الإيميل يبدو غير صحيح، أعد كتابته أو اضغط تخطي.')
            return EMAIL
    db.update(ctx.user_data['order_id'], email=email)
    sender = update.callback_query.message if update.callback_query else update.message
    await sender.reply_text('📝 *الخطوة 4:* عنوانك (مثال: بغداد، الكرادة)',
                            parse_mode='Markdown')
    return ADDRESS


async def got_address(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db.update(ctx.user_data['order_id'], address=update.message.text.strip())
    await update.message.reply_text(
        '📝 *الخطوة 5:* المسمى الوظيفي اللي تريد تقدم عليه\n'
        '(مثال: مندوب طبي، محاسب، مطور ويب)',
        parse_mode='Markdown')
    return JOB_TITLE


async def got_job_title(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db.update(ctx.user_data['order_id'], job_title=update.message.text.strip())
    kb = [[InlineKeyboardButton('⏭️ تخطي', callback_data='tjob:skip')]]
    await update.message.reply_text(
        '🎯 *خطوة اختيارية:* شنو الوظيفة أو المجال اللي تستهدفها بهذا السيفي؟\n'
        '(مثال: مندوب طبي بشركات الأدوية)\n'
        'هذي المعلومة تساعد الذكاء الاصطناعي يخصص الملخص والمهارات لك.',
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(kb))
    return TARGET_JOB


async def got_target_job(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db.update(ctx.user_data['order_id'], target_job=update.message.text.strip())
    return await _ask_summary(update, ctx)


async def skip_target_job(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    db.update(ctx.user_data['order_id'], target_job='')
    return await _ask_summary(update, ctx)


async def _ask_summary(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton('🤖 خلي الذكاء الاصطناعي يكتبه', callback_data='sum:skip')]]
    msg = update.callback_query.message if update.callback_query else update.message
    await msg.reply_text(
        '📝 *الخطوة 6:* الملخص المهني\n'
        'تكدر تكتبه بنفسك بجملتين أو ثلاثة، أو تخلي الذكاء الاصطناعي يكتبه لك '
        'من معلوماتك.',
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(kb))
    return SUMMARY


async def skip_summary(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    # leave summary empty — AIBuilder will generate it at preview time
    db.update(ctx.user_data['order_id'], summary='')
    await q.message.reply_text(
        '🤖 تمام — الذكاء الاصطناعي رح يكتب الملخص من معلوماتك.\n\n'
        '💼 *الخبرات العملية*\nاكتب المسمى الوظيفي للخبرة الأولى\n(مثال: مندوب مبيعات)',
        parse_mode='Markdown')
    return EXP_TITLE


async def got_summary(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    order_id = ctx.user_data['order_id']
    user_summary = update.message.text.strip()
    db.update(order_id, summary=user_summary)
    # AI calls below can take up to ~60s — tell the user we're working
    await update.message.reply_text('✍️ جاري تحسين الملخص...')
    # AI polish (rule-based fallback if no LLM)
    d = db.get_data(order_id)
    lang = d.get('lang') or 'ar'
    engine = get_engine()
    improved = await engine.improve_experience(user_summary, lang)
    # also offer auto-generated from data
    auto = await engine.write_summary(d, lang)
    ctx.user_data['sum_options'] = {'orig': user_summary,
                                    'improved': improved, 'auto': auto}
    kb = [[InlineKeyboardButton('✅ اعتماد ملخصي الأصلي', callback_data='sum:orig')],
          [InlineKeyboardButton('✨ استخدام المحسّن', callback_data='sum:improved')],
          [InlineKeyboardButton('🤖 استخدام المولّد تلقائيًا', callback_data='sum:auto')]]
    await update.message.reply_text(
        f'📝 *ملخصك:*\n{user_summary}\n\n'
        f'✨ *المحسّن:*\n{improved}\n\n'
        f'🤖 *المولّد تلقائيًا:*\n{auto}\n\n'
        'اختر النسخة اللي تعجبك:',
        parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    return SUMMARY_REVIEW


async def summary_pick(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    choice = q.data.split(':')[1]
    picked = ctx.user_data.get('sum_options', {}).get(choice, '')
    if picked:
        db.update(ctx.user_data['order_id'], summary=picked)
    await q.message.reply_text(
        '💼 *الخبرات العملية*\nاكتب المسمى الوظيفي للخبرة الأولى\n(مثال: مندوب مبيعات)',
        parse_mode='Markdown')
    return EXP_TITLE


async def got_exp_title(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data['exp'] = {'title': update.message.text.strip()}
    await update.message.reply_text('🏢 اسم الشركة / جهة العمل؟',
                                    parse_mode='Markdown')
    return EXP_COMPANY


async def got_exp_company(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data['exp']['company'] = update.message.text.strip()
    await update.message.reply_text('📅 الفترة الزمنية؟ (مثال: 2022 - 2024 أو 2023 - حتى الآن)',
                                    parse_mode='Markdown')
    return EXP_PERIOD


async def got_exp_period(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data['exp']['period'] = update.message.text.strip()
    await update.message.reply_text('📋 اوصف مهامك وإنجازاتك بهالوظيفة (سطر لكل مهمة)',
                                    parse_mode='Markdown')
    return EXP_DESC


async def got_exp_desc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data['exp']['desc'] = update.message.text.strip()
    ctx.user_data['exps'].append(ctx.user_data['exp'])
    kb = [[InlineKeyboardButton('➕ نعم، أضف خبرة', callback_data='exp:yes')],
          [InlineKeyboardButton('✅ لا، كافي', callback_data='exp:no')]]
    await update.message.reply_text('تريد تضيف خبرة ثانية؟',
                                    reply_markup=InlineKeyboardMarkup(kb))
    return EXP_MORE


async def exp_more(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == 'exp:yes':
        await q.message.reply_text('💼 المسمى الوظيفي للخبرة التالية؟')
        return EXP_TITLE
    db.set_json(ctx.user_data['order_id'], 'experience', ctx.user_data['exps'])
    await q.message.reply_text(
        '🎓 *الخطوة 7:* اكتب مؤهلك الدراسي\n'
        '(مثال: بكالوريوس صيدلة — جامعة بغداد، 2023)\n'
        'إذا عندك أكثر من واحد، كل واحد بسطر',
        parse_mode='Markdown')
    return EDUCATION


async def got_education(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db.update(ctx.user_data['order_id'], education=update.message.text.strip())
    kb = [[InlineKeyboardButton('⏭ تخطي', callback_data='skip:certs')]]
    await update.message.reply_text(
        '🏅 *الخطوة 8:* الشهادات والدورات (كل وحدة بسطر)\nأو تخطي إذا ما عندك',
        parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    return CERTS


async def got_certs(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        certs = []
        sender = update.callback_query.message
    else:
        certs = [l.strip() for l in update.message.text.split('\n') if l.strip()]
        sender = update.message
    db.set_json(ctx.user_data['order_id'], 'certs', certs)
    await sender.reply_text(
        '🛠 *الخطوة 9:* مهاراتك (كل مهارة بسطر)\n'
        '(مثال: التواصل، إكسل، القيادة)',
        parse_mode='Markdown')
    return SKILLS


async def got_skills(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    skills = [l.strip() for l in update.message.text.split('\n') if l.strip()]
    db.set_json(ctx.user_data['order_id'], 'skills', skills)
    kb = [[InlineKeyboardButton('⏭ تخطي', callback_data='skip:langs')]]
    await update.message.reply_text(
        '🌍 *الخطوة 10:* اللغات اللي تتقنها (كل وحدة بسطر، مثال: العربية — ممتاز)\n'
        'أو تخطي',
        parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    return LANGS_KNOWN


async def got_langs(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        langs = []
        sender = update.callback_query.message
    else:
        langs = [l.strip() for l in update.message.text.split('\n') if l.strip()]
        sender = update.message
    db.set_json(ctx.user_data['order_id'], 'languages', langs)
    order_id = ctx.user_data['order_id']
    d = db.get(order_id)
    cv_lang = d.get('lang') or 'ar'
    tmpls = db.ready_templates(cv_lang if cv_lang != 'both' else 'ar')
    if not tmpls:
        tmpls = db.ready_templates('en')
    kb = [[InlineKeyboardButton(template_label(t), callback_data=f"tmpl:{t['id']}")]
          for t in tmpls]
    kb.append([InlineKeyboardButton('🔙 رجوع', callback_data='tmpl:back')])
    await sender.reply_text('🎨 *اختر القالب* (المعروض فقط الجاهز)',
                            parse_mode='Markdown',
                            reply_markup=InlineKeyboardMarkup(kb))
    return DESIGN


# ================= template + photo + preview =================
async def pick_design(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    tid = q.data.split(':', 1)[1]
    order_id = ctx.user_data['order_id']
    if tid == 'back':
        await q.message.reply_text('رجعت لاختيار القالب — أرسل /start للبدء من جديد.')
        return ConversationHandler.END
    t = get_template(tid)
    if not t or not t['ready']:
        await q.message.reply_text('⚠️ هذا القالب غير متاح حاليًا.')
        return DESIGN
    design_key = t['design_key'] or design_for_template(tid)
    db.update(order_id, template_id=tid, design=design_key, status='template')
    kb = [[InlineKeyboardButton('📷 نعم، أرفع صورة', callback_data='photo:yes')],
          [InlineKeyboardButton('🚫 بدون صورة', callback_data='photo:no')]]
    await q.message.reply_text(
        'تريد تضيف صورتك الشخصية للسيفي؟\n(اختياري — قوالب ATS تُفضل بدون صورة)',
        reply_markup=InlineKeyboardMarkup(kb))
    return PHOTO_CHOICE


async def photo_choice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == 'photo:yes':
        await q.message.reply_text('📷 أرسل صورتك الشخصية (JPG/PNG)')
        return PHOTO_WAIT
    return await _make_preview(update, ctx)


async def photo_received(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    order_id = ctx.user_data['order_id']
    photo = update.message.photo[-1]
    odir = order_dir(order_id)
    raw_path = os.path.join(odir, 'photo_raw.jpg')
    ppath = os.path.join(odir, 'photo.jpg')
    tg_file = await photo.get_file()
    await tg_file.download_to_drive(raw_path)
    # smart 1:1 crop with face preservation
    try:
        res = photomod.crop_square(raw_path, ppath)
    except Exception:
        log.exception('photo crop failed')
        res = {'ok': False, 'reason': 'error'}
    if not res.get('ok') and res.get('reason') == 'multiple_faces':
        await update.message.reply_text(
            '👥 اكتشفت أكثر من وجه بالصورة. أرسل صورة فيها وجهك فقط '
            'بوضوح، أو اختر «بدون صورة».')
        return PHOTO_WAIT
    if not res.get('ok'):
        # fallback: use raw
        import shutil
        shutil.copy(raw_path, ppath)
    db.update(order_id, photo_path=ppath)
    # show cropped preview for confirmation
    kb = [[InlineKeyboardButton('✅ الصورة تمام', callback_data='photo:ok')],
          [InlineKeyboardButton('🔄 أرفع صورة ثانية', callback_data='photo:retry')]]
    note = ('✅ تم قص الصورة بمقاس 1:1 مع الحفاظ على الوجه.'
            if res.get('face_found') else
            '✅ تم قص الصورة بمقاس 1:1 (لم يتم اكتشاف وجه بوضوح — '
            'تأكد أن وجهك ظاهر بالمنتصف).')
    await update.message.reply_photo(
        photo=open(ppath, 'rb'), caption=note,
        reply_markup=InlineKeyboardMarkup(kb))
    return PHOTO_WAIT


async def photo_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == 'photo:retry':
        await q.message.reply_text('📷 أرسل الصورة الجديدة:')
        return PHOTO_WAIT
    return await _make_preview(update, ctx)


async def _make_preview(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    order_id = ctx.user_data['order_id']
    db.update(order_id, status='preview')
    msg = update.callback_query.message if update.callback_query else update.message
    await msg.reply_text('🤖 الذكاء الاصطناعي يبني سيرتك الذاتية...\n'
                         '✍️ كتابة الملخص المهني\n'
                         '💼 تحسين الخبرات\n'
                         '🎯 مراجعة شاملة')
    try:
        report = await _ai_enhance_order(order_id)
        log.info('AI build report for %s: %s', order_id, report)
    except Exception:
        log.exception('AI enhance failed, continuing with raw data')
    await msg.reply_text('⏳ جاري تجهيز المعاينة...')
    try:
        await build_files(order_id, preview_only=True)
    except Exception:
        log.exception('preview build failed')
        await msg.reply_text('⚠️ صار خطأ بتوليد المعاينة. حاول بـ /start')
        return ConversationHandler.END
    d = db.get(order_id)
    t = get_template(d.get('template_id') or '')
    tname = t['name_ar'] if t else d.get('design')
    png = os.path.join(order_dir(order_id), 'preview.png')
    kb = [[InlineKeyboardButton('✅ يعجبني، أكمل للدفع', callback_data='pay:yes')],
          [InlineKeyboardButton('🎨 غيّر القالب', callback_data='pay:change')]]
    await msg.reply_photo(
        photo=open(png, 'rb'),
        caption=f'👀 معاينة سيفيك — *{tname}*\n'
                '⚠️ نسخة معاينة بعلامة مائية — ليست نهائية.\n\n'
                'إذا عجبك أكمل للدفع.',
        parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    return PREVIEW_OK


async def build_files(order_id, preview_only=False):
    """Build final files (PDF+DOCX) or watermarked preview PNG only."""
    d = db.get_data(order_id)
    langs = ['ar', 'en'] if d['lang'] == 'both' else [d['lang']]
    odir = order_dir(order_id)
    design = d.get('design') or 'formal'
    photo = d.get('photo_path')
    if preview_only:
        lg = 'ar' if d['lang'] in ('ar', 'both') else 'en'
        generate_preview(d, lg, design,
                         os.path.join(odir, 'preview.png'),
                         photo_path=photo)
        return
    gate_reports = {}
    for lg in langs:
        suffix = f'_{lg}' if d['lang'] == 'both' else ''
        pdf_path = os.path.join(odir, f'cv{suffix}.pdf')
        generate_pdf(d, lg, design, pdf_path, photo_path=photo)
        generate_docx(d, lg, design, os.path.join(odir, f'cv{suffix}.docx'))
        # QUALITY GATE: mandatory post-generation check before delivery
        try:
            from ai.quality_gate import quality_gate
            jd = d.get('job_description', '')
            passed, greport = quality_gate(pdf_path, d, design, lg, jd)
            gate_reports[lg] = greport
            db.update(order_id, **{f'gate_report_{lg}': __import__('json').dumps(greport, ensure_ascii=False)})
            if not passed:
                raise RuntimeError(
                    f"Quality gate BLOCKED delivery for {lg}: "
                    f"{greport.get('critical_errors')}")
        except RuntimeError:
            raise
        except Exception as e:
            # Gate itself failed - log but don't silently pass
            gate_reports[lg] = {'passed': False, 'gate_error': str(e)}
            raise RuntimeError(f'Quality gate error for {lg}: {e}')
    # anti-fabrication snapshot at build time
    if not d.get('original_data'):
        db.update(order_id, original_data=antifab.snapshot_original(d))


async def preview_choice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    order_id = ctx.user_data['order_id']
    if q.data == 'pay:change':
        d0 = db.get(order_id)
        tmpls = db.ready_templates((d0.get('lang') if d0 else None) or 'ar')
        if not tmpls:
            tmpls = db.ready_templates('en')
        kb = [[InlineKeyboardButton(template_label(t), callback_data=f"tmpl:{t['id']}")]
              for t in tmpls]
        await q.message.reply_text('🎨 اختر القالب الجديد:',
                                   reply_markup=InlineKeyboardMarkup(kb))
        return DESIGN
    if not await _guard_keycard(q, ctx):
        return DESIGN  # misconfigured: stay on design step, show nothing wrong
    db.update(order_id, status='awaiting_payment')
    text = (
        '💳 *الدفع عبر كي كارد*\n\n'
        f'🔢 رقم البطاقة: `{KEYCARD_NUMBER}`\n'
        f'💰 المبلغ: *{PRICE} دينار عراقي*\n'
        f'🧾 رقم الطلب: `{order_id}`\n\n'
        '⚠️ اكتب رقم الطلب بملاحظة التحويل.\n'
        'بعد التحويل أرسل *صورة إثبات الدفع* هنا 👇'
    )
    await q.message.reply_text(text, parse_mode='Markdown')
    return PROOF


# ================= payment proof =================
async def _send_admin_review_card(ctx, order_id, photo_file_id,
                                      attempt=None, verify_result=None):
    """Admin review card for a receipt (first upload, clearer resend, re-upload)."""
    d = db.get(order_id)
    t = get_template(d.get('template_id') or '')
    exp_txt = '\n'.join(
        f"• {e.get('title','')} @ {e.get('company','')} ({e.get('period','')})"
        for e in (db.get_data(order_id)['experience'] or []))
    att_txt = (f'\n🔄 محاولة إعادة الرفع: {attempt}/{REUPLOAD_MAX}'
               if attempt else '')
    # Verification summary for admin (masked sensitive data)
    vtxt = ''
    if verify_result:
        dec = verify_result.get('decision', '?')
        reason = verify_result.get('reason', '?')
        conf = verify_result.get('confidence', '?')
        fields = verify_result.get('fields', {})
        analysis = fields.get('analysis', {})
        amt_info = ''
        if 'amount_match' in fields:
            amt_info = (f"\n💰 المبلغ: {'✅ مطابق' if fields['amount_match'] else '⚠️ غير مطابق'} "
                        f"(المطلوب: {fields.get('expected', '?')})")
        dup_info = ''
        if fields.get('duplicate', {}).get('is_duplicate'):
            dup_info = (f"\n🚨 *اشتباه إعادة استخدام*: {fields['duplicate'].get('match_type')} "
                        f"(طلب: `{fields['duplicate'].get('matched_order')}`)")
        vtxt = (f"\n\n🔍 *فحص آلي*: {dec} ({conf})\n"
                f"السبب: `{reason}`{amt_info}{dup_info}"
                f"\nالتصنيف: {analysis.get('classification', '?')}")
        if not verify_result.get('ocr_available'):
            vtxt += "\n⚠️ OCR غير متاح — المراجعة يدوية بالكامل"
    admin_text = (
        '🧾 *طلب دفع جديد*\n\n'
        f'رقم الطلب: `{order_id}`\n'
        f'{vtxt}\n'
        f'الاسم: {d.get("full_name")}\n'
        f'الهاتف: {d.get("phone")}\n'
        f'اللغة: {LANG_NAMES.get(d.get("lang"), d.get("lang"))}\n'
        f'القالب: {t["name_ar"] if t else d.get("design")}\n'
        f'الخبرات:\n{exp_txt or "—"}'
        f'{att_txt}'
    )
    kb = [[InlineKeyboardButton('✅ موافقة', callback_data=f'adm_pay:approve:{order_id}'),
           InlineKeyboardButton('❌ رفض', callback_data=f'adm_pay:reject:{order_id}')],
          [InlineKeyboardButton('🔍 طلب إيصال أوضح', callback_data=f'adm_pay:clearer:{order_id}')]]
    await ctx.bot.send_photo(
        chat_id=ADMIN_ID, photo=photo_file_id, caption=admin_text,
        parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))



async def _verify_receipt_photo(ctx, order_id, photo_file_id):
    """Download receipt, run smart verification, store result.
    Returns verification dict. Never raises."""
    import os, json
    result = {'decision': 'manual_review', 'reason': 'verify_error'}
    try:
        from ai.receipt_verify import verify_receipt, record_receipt
        # Download photo
        tg_file = await ctx.bot.get_file(photo_file_id)
        dl_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              'orders', order_id)
        os.makedirs(dl_dir, exist_ok=True)
        dl_path = os.path.join(dl_dir, f'receipt_{photo_file_id[:12]}.jpg')
        await tg_file.download_to_drive(dl_path)
        # Get expected amount from order
        d = db.get(order_id) or {}
        expected = d.get('price') or 5000
        try:
            expected = int(expected)
        except (ValueError, TypeError):
            expected = 5000
        # Verify
        result = verify_receipt(dl_path, expected, order_id, db.DB_PATH)
        # Store result (truncated, no sensitive full data in main table)
        store = {k: v for k, v in result.items()
                 if not k.startswith('_')}
        # Keep txn refs for duplicate tracking (internal)
        txn_refs = result.get('fields', {}).get('_txn_refs_full', [])
        sha_full = result.get('fields', {}).get('_sha_full', '')
        phash = result.get('fields', {}).get('phash', '')
        try:
            db.update(order_id,
                      receipt_verify=json.dumps(store, ensure_ascii=False)[:2000],
                      receipt_path=dl_path)
        except Exception:
            pass
        # Record hashes for future duplicate detection
        if sha_full:
            record_receipt(db.DB_PATH, order_id, sha_full, phash or '',
                           txn_refs or [])
        db.audit(0, 'receipt_verified',
                 f"{order_id}: {result['decision']}/{result['reason']}")
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception('receipt verify failed')
        result = {'decision': 'manual_review', 'reason': f'verify_error:{e}'}
    return result

async def got_proof(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    order_id = ctx.user_data.get('order_id')
    if not order_id:
        await update.message.reply_text('⚠️ انتهت الجلسة — أرسل /start وابدأ من جديد.')
        return ConversationHandler.END
    photo = update.message.photo[-1]
    # atomic: only unpaid/awaiting_receipt may move to under_review.
    # A receipt after approval/delivery/rejection is politely refused here;
    # post-rejection re-uploads go through the reup: button + photo router.
    if not db.cas_payment_review(order_id, photo.file_id):
        cur = db.get(order_id)
        ps = (cur or {}).get('payment_status')
        if ps == 'under_review':
            await update.message.reply_text('⏳ إيصالك قيد المراجعة already — انتظر النتيجة.')
        elif ps in ('approved', 'rejected', 'closed'):
            await update.message.reply_text(
                '⚠️ لا يمكن استلام إيصال جديد لهذا الطلب بهذه المرحلة.')
        else:
            await update.message.reply_text('⚠️ هذا الطلب غير موجود أو ليس لك.')
        return ConversationHandler.END
    # Smart receipt verification (never auto-approves)
    vres = await _verify_receipt_photo(ctx, order_id, photo.file_id)
    if vres['decision'] == 'rejected':
        # Invalid image: tell user immediately, revert to awaiting
        db.update(order_id, payment_status='awaiting_receipt')
        db.audit(update.effective_user.id, 'receipt_auto_rejected',
                 f"{order_id}: {vres['reason']}")
        await update.message.reply_text(
            '⚠️ الصورة المرسلة غير صالحة كإيصال دفع.\n'
            'أرسل صورة واضحة لإيصال التحويل المكتمل.')
        return ConversationHandler.END
    await _send_admin_review_card(ctx, order_id, photo.file_id,
                                  verify_result=vres)
    await update.message.reply_text(
        '✅ استلمنا إثبات الدفع.\n⏳ جاري المراجعة — نبلغك بالنتيجة قريبًا.')
    return ConversationHandler.END


def _reupload_window_open(d):
    """True if we are still inside the REUPLOAD_WINDOW_DAYS window after rejection."""
    ts = d.get('rejected_at')
    if not ts:
        return True  # legacy rows without timestamp: allow
    try:
        rej = datetime.datetime.fromisoformat(ts)
    except Exception:
        return True
    return (datetime.datetime.now() - rej).days < REUPLOAD_WINDOW_DAYS


async def receipt_photo_route(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Standalone photo handler (group=-1): consumes a photo ONLY when the user
    was explicitly asked for one via the re-upload or clearer flows
    (ctx.user_data['awaiting_receipt']). Runs before the conversation handlers;
    stops propagation when it handles the photo so the conv never double-processes.

    This fixes the old 'clearer' flow, which asked the user for a photo while no
    conversation state was listening — the photo was silently ignored.
    """
    pend = ctx.user_data.get('awaiting_receipt')
    if not pend:
        return  # not ours — let the conversation handle it
    ctx.user_data.pop('awaiting_receipt', None)
    order_id = pend.get('order_id')
    mode = pend.get('mode')
    d = db.get(order_id) if order_id else None
    if not d or d['user_id'] != update.effective_user.id:
        await update.message.reply_text('⚠️ هذا الطلب غير موجود أو ليس لك.')
        raise ApplicationHandlerStop
    photo = update.message.photo[-1]
    if mode == 'clearer':
        if not db.cas_payment_review(order_id, photo.file_id):
            await update.message.reply_text('⚠️ لم نعد بانتظار إيصال أوضح لهذا الطلب.')
            raise ApplicationHandlerStop
        db.audit(update.effective_user.id, 'receipt_resent_clearer', order_id)
        await _send_admin_review_card(ctx, order_id, photo.file_id)
    elif mode == 'reupload':
        att = (d.get('reupload_count') or 0) + 1
        if att > REUPLOAD_MAX or not _reupload_window_open(d):
            db.update(order_id, status='closed')
            db.audit(update.effective_user.id, 'reupload_window_expired',
                     f'{order_id} attempts={d.get("reupload_count") or 0}')
            await update.message.reply_text(
                '🔒 انتهت محاولات/مهلة إعادة رفع الإيصال — أُغلق الطلب.\n'
                'لإنشاء طلب جديد أرسل /start.')
            raise ApplicationHandlerStop
        if not db.cas_reupload_review(order_id, photo.file_id, att):
            await update.message.reply_text('⚠️ لم نعد بانتظار إيصال لهذا الطلب.')
            raise ApplicationHandlerStop
        db.audit(update.effective_user.id, 'receipt_reuploaded',
                 f'{order_id} attempt={att}/{REUPLOAD_MAX}')
        await _send_admin_review_card(ctx, order_id, photo.file_id, attempt=att)
    elif mode == 'editbuy':
        db.audit(update.effective_user.id, 'edit_receipt_sent', order_id)
        kb = [[InlineKeyboardButton('✅ موافقة', callback_data=f'adm_edt:approve:{order_id}'),
               InlineKeyboardButton('❌ رفض', callback_data=f'adm_edt:reject:{order_id}')]]
        await ctx.bot.send_photo(
            chat_id=ADMIN_ID, photo=photo.file_id,
            caption=(f'🧾 *شراء حزمة تعديلات*\n\n'
                     f'رقم الطلب: `{order_id}`\n'
                     f'الزبون: {update.effective_user.full_name} (@{update.effective_user.username})\n'
                     f'الاسم: {d.get("full_name")}\n'
                     f'الرصيد الحالي: {d.get("edits_free_left", 0)} مجاني / {d.get("edits_paid_left", 0)} مدفوع'),
            parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    else:
        raise ApplicationHandlerStop
    await update.message.reply_text(
        '✅ استلمنا إثبات الدفع.\n⏳ جاري المراجعة — نبلغك بالنتيجة قريبًا.')
    raise ApplicationHandlerStop


async def stray_photo_fallback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Catch-all for photos no conversation state consumed (registered in the
    same group right after the main conversation: within a group only the
    first matching handler runs, so this fires only when the conv ignored the
    photo). Politely refuses it as a receipt — receipts are ONLY accepted via
    got_proof (PROOF state) or the armed receipt_photo_route, never here."""
    await update.message.reply_text(
        '⚠️ لا يمكن استلام إيصال جديد بهذه المرحلة.\n'
        'إذا كان لديك طلب بانتظار الدفع، افتحه من 📋 طلباتي.')


async def user_reupload_request(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """User button '🔄 إعادة رفع الإيصال' on the rejection message."""
    q = update.callback_query
    order_id = q.data.split(':', 1)[1]
    d = db.get(order_id)
    if not d or d['user_id'] != q.from_user.id:
        await q.answer('⛔ هذا الطلب ليس لك.', show_alert=True)
        return
    if d.get('payment_status') != 'rejected':
        await q.answer('ℹ️ هذا الطلب ليس بحالة رفض.', show_alert=True)
        return
    att = d.get('reupload_count') or 0
    if att >= REUPLOAD_MAX or not _reupload_window_open(d):
        db.update(order_id, status='closed')
        db.audit(q.from_user.id, 'reupload_window_expired',
                 f'{order_id} attempts={att}')
        await q.answer('انتهت محاولات إعادة الرفع.', show_alert=True)
        await q.message.reply_text(
            '🔒 أُغلق الطلب بعد استنفاد محاولات/مهلة إعادة رفع الإيصال.\n'
            'لإنشاء طلب جديد أرسل /start.')
        return
    await q.answer()
    ctx.user_data['awaiting_receipt'] = {'order_id': order_id, 'mode': 'reupload'}
    await q.message.reply_text(
        f'🔄 *إعادة رفع الإيصال* — الطلب `{order_id}`\n\n'
        f'المحاولة {att + 1} من {REUPLOAD_MAX}.\n'
        '📸 أرسل صورة الإيصال الصحيح هنا 👇',
        parse_mode='Markdown')


REJECT_REASONS = {
    'unclear': 'الصورة غير واضحة',
    'amount': 'المبلغ غير مكتمل',
    'duplicate': 'إيصال مستخدم لطلب آخر',
    'test': 'طلب اختبار',
    'other': 'سبب آخر',
}


# ================= admin payment decisions =================
async def _fulfill_order(ctx, order_id, admin_id):
    """Generation + quality gate + delivery pipeline after payment approval
    (or admin regen). Payment stays 'approved' throughout — a failure here
    never asks the user to pay again (mega-prompt §6)."""
    d0 = db.get(order_id)
    # IDEMPOTENCY: if already delivered, don't deliver twice
    # (crash between _deliver_order and status update)
    if d0.get('status') == 'delivered':
        db.audit(admin_id, 'fulfill_skipped_already_delivered', order_id)
        return
    user_id = d0['user_id']
    regen_kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton('🔁 إعادة التوليد (مجاني)',
                               callback_data=f'adm_pay:regen:{order_id}')]])
    # ---- generation ----
    try:
        await build_files(order_id)
    except Exception:
        log.exception('generation failed after approval')
        db.update(order_id, status='quality_failed')
        db.audit(admin_id, 'generation_failed', order_id)
        await ctx.bot.send_message(
            chat_id=user_id,
            text='⚠️ صار خلل تقني بالتوليد — نعيد المحاولة مجانًا بدون دفع جديد.')
        await ctx.bot.send_message(
            chat_id=ADMIN_ID,
            text=f'⚠️ فشل توليد الطلب `{order_id}` بعد الموافقة — يحتاج تدخل.',
            parse_mode='Markdown', reply_markup=regen_kb)
        return
    db.update(order_id, status='quality_check')
    qr = quality.run_quality(order_dir(order_id), db.get_data(order_id),
                             db.get(order_id).get('lang') or 'ar')
    if not qr.passed:
        db.update(order_id, status='quality_failed',
                  quality_status=';'.join(c for c, _ in qr.issues))
        db.audit(admin_id, 'quality_failed',
                 f"{order_id}: {';'.join(c for c, _ in qr.issues)}")
        await ctx.bot.send_message(
            chat_id=user_id,
            text='⚠️ فشل فحص الجودة — نصلح المشكلة ونعيد التوليد مجانًا.')
        await ctx.bot.send_message(
            chat_id=ADMIN_ID,
            text=f'🚨 فشل فحص الجودة للطلب `{order_id}`:\n' +
                 '\n'.join(f'• {c}: {dt}' for c, dt in qr.issues[:8]),
            parse_mode='Markdown', reply_markup=regen_kb)
        return
    # anti-fabrication check
    dd = db.get_data(order_id)
    changes = antifab.compare(dd.get('original_data'), dd)
    sens = antifab.sensitive_changed(changes)
    if sens:
        db.audit(admin_id, 'antifab_flag', f"{order_id}: {sens}")
    db.update(order_id, status='ready', quality_status='passed')
    # ---- deliver ----
    await _deliver_order(ctx, order_id)
    db.update(order_id, status='delivered')
    db.audit(admin_id, 'order_delivered', order_id)
    await ctx.bot.send_message(chat_id=ADMIN_ID,
                               text=f'✅ تم تسليم الطلب `{order_id}`.',
                               parse_mode='Markdown')


async def admin_pay_decision(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not check_admin(q.from_user.id, ADMIN_ID):
        await q.answer('⛔ للإدارة فقط.', show_alert=True)
        return
    _, action, rest = q.data.split(':', 2)
    # rejreason format: adm_pay:rejreason:ORDER:reason -> order_id itself may not
    # contain ':', but the naive split above would glue the reason onto it.
    reason_key = None
    if action == 'rejreason':
        *oid_parts, reason_key = rest.split(':')
        order_id = ':'.join(oid_parts)
    else:
        order_id = rest
    d = db.get_data(order_id)
    if not d:
        await q.answer('⚠️ الطلب غير موجود.', show_alert=True)
        return
    user_id = d['user_id']

    if action == 'regen':
        # admin re-generation after post-approval failure — no new payment.
        # Atomic claim: only one regen runs even on double-click / redelivery.
        await q.answer()
        if not db.cas_regen_start(order_id):
            await q.message.reply_text(
                '⚠️ إعادة التوليد متاحة فقط للطلبات مدفوعة الثمن وفاشلة التوليد.')
            return
        db.audit(q.from_user.id, 'regen_started', order_id)
        await q.message.reply_text(f'🔁 بدأ إعادة توليد `{order_id}`…',
                                   parse_mode='Markdown')
        await ctx.bot.send_message(
            chat_id=user_id,
            text='🔁 نعيد توليد سيفيك مجانًا — بدون دفع جديد.')
        await _fulfill_order(ctx, order_id, q.from_user.id)
        return

    # approve / reject / clearer / rejreason — allowed ONLY from under_review.
    # Every transition below is an atomic compare-and-set, so a double-click
    # or a redelivered callback_query cannot act twice.
    if d.get('payment_status') != 'under_review':
        await q.answer('⚠️ تم اتخاذ قرار already لهذا الطلب — لا يمكن التكرار.',
                       show_alert=True)
        return
    await q.answer()

    if action == 'clearer':
        if not db.cas_update(order_id, {'payment_status': 'under_review'},
                             payment_status='awaiting_receipt'):
            await q.answer('⚠️ تغيّرت الحالة already.', show_alert=True)
            return
        db.audit(q.from_user.id, 'payment_clearer_requested', order_id)
        _n1 = '\n\n🔍 *طُلب إيصال أوضح*'
        try:
            if q.message.caption is not None:
                await q.message.edit_caption(caption=q.message.caption + _n1, parse_mode='Markdown')
            else:
                await q.message.edit_text((q.message.text or '') + _n1, parse_mode='Markdown')
        except Exception:
            pass
        await ctx.bot.send_message(
            chat_id=user_id,
            text=f'🔍 نحتاج صورة أوضح لإيصال الطلب `{order_id}`.\nأرسلها هنا.',
            parse_mode='Markdown')
        # arm the standalone photo router (the old code set user_data['order_id']
        # but no conversation state was listening — the photo was ignored)
        ctx.user_data['awaiting_receipt'] = {'order_id': order_id, 'mode': 'clearer'}
        return

    if action == 'reject':
        kb = [[InlineKeyboardButton(v, callback_data=f'adm_pay:rejreason:{order_id}:{k}')]
              for k, v in REJECT_REASONS.items()]
        _n3 = '\n\n❌ *بانتظار اختيار سبب الرفض*'
        try:
            if q.message.caption is not None:
                await q.message.edit_caption(caption=q.message.caption + _n3, parse_mode='Markdown')
            else:
                await q.message.edit_text((q.message.text or '') + _n3, parse_mode='Markdown')
        except Exception:
            pass
        await q.message.reply_text('اختر سبب الرفض:', reply_markup=InlineKeyboardMarkup(kb))
        return

    if action == 'rejreason':
        reason = REJECT_REASONS.get(reason_key, 'غير محدد')
        if not db.cas_update(order_id, {'payment_status': 'under_review'},
                             payment_status='rejected', status='rejected',
                             reject_reason=reason, rejected_at=db._now()):
            await q.answer('⚠️ تم اتخاذ قرار already.', show_alert=True)
            return
        db.audit(q.from_user.id, 'payment_rejected', f'{order_id}: {reason}')
        await q.message.edit_text(f'❌ رُفض الطلب `{order_id}` — السبب: {reason}',
                                  parse_mode='Markdown')
        kb = [[InlineKeyboardButton('🔄 إعادة رفع الإيصال',
                                    callback_data=f'reup:{order_id}')]]
        await ctx.bot.send_message(
            chat_id=user_id,
            text=(f'❌ عذرًا، رُفض إثبات الدفع للطلب `{order_id}`.\n'
                  f'السبب: {reason}\n\n'
                  f'🔄 يمكنك إعادة رفع إيصال صحيح — {REUPLOAD_MAX} محاولات '
                  f'خلال {REUPLOAD_WINDOW_DAYS} أيام من الرفض.'),
            parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
        return

    if action == 'approve':
        if not db.cas_update(order_id, {'payment_status': 'under_review'},
                             payment_status='approved', status='generating',
                             approved_by=q.from_user.id, approved_at=db._now()):
            await q.answer('⚠️ تمت الموافقة already على هذا الطلب.', show_alert=True)
            return
        db.audit(q.from_user.id, 'payment_approved', order_id)
        _n2 = '\n\n✅ *مقبول — جاري التوليد*'
        try:
            if q.message.caption is not None:
                await q.message.edit_caption(caption=q.message.caption + _n2, parse_mode='Markdown')
            else:
                await q.message.edit_text((q.message.text or '') + _n2, parse_mode='Markdown')
        except Exception:
            pass
        await ctx.bot.send_message(chat_id=user_id,
                                   text='✅ تم قبول الدفع! جاري توليد سيفيك النهائي...')
        await _fulfill_order(ctx, order_id, q.from_user.id)
        return


async def _deliver_order(ctx, order_id):
    d = db.get_data(order_id)
    user_id = d['user_id']
    odir = order_dir(order_id)
    langs = ['ar', 'en'] if d['lang'] == 'both' else [d['lang']]
    for lg in langs:
        suffix = f'_{lg}' if d['lang'] == 'both' else ''
        pdf_p = os.path.join(odir, f'cv{suffix}.pdf')
        docx_p = os.path.join(odir, f'cv{suffix}.docx')
        if os.path.exists(pdf_p):
            await ctx.bot.send_document(chat_id=user_id, document=open(pdf_p, 'rb'),
                                        filename=f'CV_{order_id}{suffix}.pdf')
        if os.path.exists(docx_p):
            await ctx.bot.send_document(chat_id=user_id, document=open(docx_p, 'rb'),
                                        filename=f'CV_{order_id}{suffix}.docx')
    for lg in langs:
        cl = make_cover_letter(d, lg)
        await ctx.bot.send_message(
            chat_id=user_id,
            text=f'✉️ *خطاب التقديم ({LANG_NAMES[lg]}) — مجاني:*\n\n{cl}',
            parse_mode='Markdown')
    kb = [[InlineKeyboardButton('✏️ طلب تعديل', callback_data=f'edit:{order_id}')],
          [InlineKeyboardButton('🔧 الإبلاغ عن خطأ بالنظام',
                                callback_data=f'syserr:{order_id}')]]
    dd = db.get(order_id)
    await ctx.bot.send_message(
        chat_id=user_id,
        text='🎉 *تم! سيفيك جاهز*\n\n'
             'استلمت PDF + Word + خطاب التقديم.\n'
             f"رصيد التعديل: {dd.get('edits_free_left', 2)} مجاني.",
        parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    # professional memory consent (once)
    try:
        await feat.memory_consent_prompt(ctx, user_id, d)
    except Exception:
        pass
    # Ask for rating (once per order, only after successful delivery)
    try:
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        existing = conn.execute(
            "SELECT 1 FROM ratings WHERE order_id=?", (order_id,)).fetchone()
        conn.close()
        if not existing:
            kb_rate = InlineKeyboardMarkup([
                [InlineKeyboardButton('1️⃣', callback_data=f'rate:{order_id}:1'),
                 InlineKeyboardButton('2️⃣', callback_data=f'rate:{order_id}:2'),
                 InlineKeyboardButton('3️⃣', callback_data=f'rate:{order_id}:3'),
                 InlineKeyboardButton('4️⃣', callback_data=f'rate:{order_id}:4'),
                 InlineKeyboardButton('5️⃣', callback_data=f'rate:{order_id}:5')],
                [InlineKeyboardButton('6️⃣', callback_data=f'rate:{order_id}:6'),
                 InlineKeyboardButton('7️⃣', callback_data=f'rate:{order_id}:7'),
                 InlineKeyboardButton('8️⃣', callback_data=f'rate:{order_id}:8'),
                 InlineKeyboardButton('9️⃣', callback_data=f'rate:{order_id}:9'),
                 InlineKeyboardButton('🔟', callback_data=f'rate:{order_id}:10')],
            ])
            await ctx.bot.send_message(
                chat_id=user_id,
                text=('⭐ *قيّم تجربتك*\n\n'
                      'نتمنى أن تكون سيرتك بالمستوى الذي تطمح إليه.\n'
                      'قيّم السيرة من 1 إلى 10 حتى نحسّن جودتنا باستمرار.'),
                parse_mode='Markdown', reply_markup=kb_rate)
    except Exception:
        pass
# ================= buy edit package: 5 edits for PRICE =================
EDIT_PACKAGE_COUNT = 5
_editbuy_processing = set()  # in-run guard against double admin approval


async def buy_edits_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """User tapped buy-5-edits button: show Keycard instructions, await receipt."""
    q = update.callback_query
    await q.answer()
    order_id = q.data.split(':', 1)[1]
    if not await _check_owns(update, ctx, order_id):
        return
    pend = ctx.user_data.get('awaiting_receipt')
    if pend and pend.get('mode') == 'editbuy' and pend.get('order_id') == order_id:
        await q.message.reply_text('⏳ أنتظر صورة إيصال حزمة التعديلات — أرسلها هنا.')
        return
    if not await _guard_keycard(q, ctx):
        return
    ctx.user_data['awaiting_receipt'] = {'order_id': order_id, 'mode': 'editbuy'}
    await q.message.reply_text(
        '💳 *شراء 5 تعديلات إضافية*\n\n'
        f'🔢 رقم البطاقة: `{KEYCARD_NUMBER}`\n'
        f'💰 المبلغ: *{PRICE} دينار عراقي*\n'
        f'🧾 رقم الطلب: `{order_id}`\n\n'
        '⚠️ اكتب رقم الطلب بملاحظة التحويل.\n'
        'بعد التحويل أرسل *صورة إثبات الدفع* هنا 👇',
        parse_mode='Markdown')


async def admin_edit_decision(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin approve/reject for edit-package purchases (manual Keycard review)."""
    q = update.callback_query
    if not check_admin(q.from_user.id, ADMIN_ID):
        await q.answer('⛔ للإدارة فقط.', show_alert=True)
        return
    await q.answer()
    _, action, rest = q.data.split(':', 2)
    reason_key = None
    if action == 'rejreason':
        *oid_parts, reason_key = rest.split(':')
        order_id = ':'.join(oid_parts)
    else:
        order_id = rest
    d = db.get(order_id)
    if not d:
        await q.message.reply_text('⚠️ الطلب غير موجود.')
        return
    if action == 'reject':
        kb = [[InlineKeyboardButton(v, callback_data=f'adm_edt:rejreason:{order_id}:{k}')]
              for k, v in REJECT_REASONS.items()]
        await q.message.reply_text('اختر سبب الرفض:', reply_markup=InlineKeyboardMarkup(kb))
        return
    if action == 'rejreason':
        reason = REJECT_REASONS.get(reason_key, 'غير محدد')
        db.audit(q.from_user.id, 'edit_purchase_rejected', f'{order_id}: {reason}')
        try:
            base = q.message.caption or ''
            await q.message.edit_caption(caption=base + f'\n\n❌ *مرفوض: {reason}*',
                                         parse_mode='Markdown', reply_markup=None)
        except Exception:
            pass
        await ctx.bot.send_message(
            chat_id=d['user_id'],
            text=f'❌ رُفض إثبات الدفع لحزمة التعديلات (الطلب `{order_id}`).\nالسبب: {reason}',
            parse_mode='Markdown')
        return
    # approve (idempotent per card: buttons removed on decision + in-run guard)
    if order_id in _editbuy_processing:
        await q.answer('المعالجة جارية already.', show_alert=True)
        return
    _editbuy_processing.add(order_id)
    try:
        cur = db.get(order_id)
        new_paid = (cur.get('edits_paid_left') or 0) + EDIT_PACKAGE_COUNT
        db.update(order_id, edits_paid_left=new_paid)
        db.audit(q.from_user.id, 'edit_purchase_approved',
                 f'{order_id} +{EDIT_PACKAGE_COUNT} (paid left now: {new_paid})')
        try:
            base = q.message.caption or ''
            await q.message.edit_caption(
                caption=base + f'\n\n✅ *معتمد — أُضيفت {EDIT_PACKAGE_COUNT} تعديلات*',
                parse_mode='Markdown', reply_markup=None)
        except Exception:
            pass
        await ctx.bot.send_message(
            chat_id=d['user_id'],
            text=f'✅ تم قبول الدفع! أُضيفت *{EDIT_PACKAGE_COUNT} تعديلات* لرصيدك.\n'
                 f'رصيدك الآن: {new_paid} مدفوعة.\nاضغط «✏️ طلب تعديل» للبدء.',
            parse_mode='Markdown')
    finally:
        _editbuy_processing.discard(order_id)


# ================= edit system: 2 free -> 5 paid -> system errors always free ====
EDIT_FIELDS = {
    'full_name': 'الاسم الكامل',
    'phone': 'رقم الهاتف',
    'email': 'الإيميل',
    'address': 'العنوان',
    'job_title': 'المسمى الوظيفي',
    'summary': 'الملخص المهني',
    'education': 'التعليم',
}

async def edit_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    order_id = q.data.split(':')[1]
    if not await _check_owns(update, ctx, order_id):
        return ConversationHandler.END
    d = db.get(order_id)
    free_left = d.get('edits_free_left', 2) or 0
    paid_left = d.get('edits_paid_left', 0) or 0
    ctx.user_data['order_id'] = order_id
    if free_left <= 0 and paid_left <= 0:
        kb = [[InlineKeyboardButton('💳 شراء 5 تعديلات (5,000 د.ع)',
                                    callback_data=f'buyedits:{order_id}')],
              [InlineKeyboardButton('🔧 الإبلاغ عن خطأ بالنظام (مجاني)',
                                    callback_data=f'syserr:{order_id}')]]
        await q.message.reply_text(
            '⚠️ انتهى رصيد التعديل المجاني.\n'
            'يمكنك شراء 5 تعديلات بـ 5,000 د.ع، أو الإبلاغ عن خطأ بالنظام (مجاني دائمًا).',
            reply_markup=InlineKeyboardMarkup(kb))
        return ConversationHandler.END
    kb = [[InlineKeyboardButton(v, callback_data=f'ef:{k}')]
          for k, v in EDIT_FIELDS.items()]
    kb.append([InlineKeyboardButton('🔧 هذا خطأ من النظام (مجاني دائمًا)',
                                    callback_data=f'syserr:{order_id}')])
    await q.message.reply_text(
        f'✏️ أي فقرة تريد تعديلها؟\nرصيدك: {free_left} مجاني / {paid_left} مدفوع',
        reply_markup=InlineKeyboardMarkup(kb))
    return EDIT_CHOICE


async def _check_owns(update, ctx, order_id):
    q = update.callback_query
    d = db.get(order_id)
    if not d:
        await q.message.reply_text('⚠️ الطلب غير موجود.')
        return False
    if d['user_id'] != q.from_user.id:
        await q.answer('⛔ هذا الطلب ليس لك.', show_alert=True)
        return False
    return True


async def edit_choice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    field = q.data.split(':')[1]
    ctx.user_data['edit_field'] = field
    ctx.user_data['edit_kind'] = 'user'
    await q.message.reply_text(f'اكتب القيمة الجديدة لـ *{EDIT_FIELDS[field]}*:',
                               parse_mode='Markdown')
    return EDIT_VALUE


async def syserr_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Separate free path: report a system error."""
    q = update.callback_query
    await q.answer()
    order_id = q.data.split(':')[1]
    if not await _check_owns(update, ctx, order_id):
        return ConversationHandler.END
    ctx.user_data['order_id'] = order_id
    ctx.user_data['edit_kind'] = 'system'
    kb = [[InlineKeyboardButton(v, callback_data=f'ef:{k}')]
          for k, v in EDIT_FIELDS.items()]
    await q.message.reply_text(
        '🔧 *الإبلاغ عن خطأ بالنظام* (مجاني دائمًا — لا يُخصم من رصيدك)\n'
        'اختر الفقرة التي فيها الخطأ:',
        parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    return EDIT_CHOICE


async def edit_value(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    order_id = ctx.user_data['order_id']
    field = ctx.user_data['edit_field']
    kind = ctx.user_data.get('edit_kind', 'user')
    new_val = update.message.text.strip()
    d = db.get(order_id)
    old_val = d.get(field) or ''
    free_left = d.get('edits_free_left', 2) or 0
    paid_left = d.get('edits_paid_left', 0) or 0

    charge_kind, charged = 'system', False
    if kind == 'system':
        charge_kind = 'system'  # always free, never deducted
    elif free_left > 0:
        charge_kind, charged = 'free', True
        db.update(order_id, edits_free_left=free_left - 1)
    elif paid_left > 0:
        charge_kind, charged = 'paid', True
        db.update(order_id, edits_paid_left=paid_left - 1)
    else:
        await update.message.reply_text('⚠️ لا رصيد متبقٍ.')
        return ConversationHandler.END

    db.update(order_id, **{field: new_val})
    db.log_edit(order_id, update.effective_user.id, charge_kind, field,
                old_val, new_val, charged)
    await update.message.reply_text('⏳ جاري إعادة توليد السيفي...')
    try:
        await build_files(order_id)
    except Exception:
        log.exception('rebuild failed')
        # rollback the charge on technical failure: no deduction
        if charge_kind == 'free':
            db.update(order_id, edits_free_left=free_left)
        elif charge_kind == 'paid':
            db.update(order_id, edits_paid_left=paid_left)
        db.log_edit(order_id, update.effective_user.id, 'system',
                    field, old_val, new_val, False)
        await update.message.reply_text(
            '⚠️ صار خلل تقني — لم يُخصم من رصيدك. حاول لاحقًا.')
        return ConversationHandler.END
    # quality re-check after edit
    dd = db.get_data(order_id)
    qr = quality.run_quality(order_dir(order_id), dd, dd.get('lang') or 'ar')
    if not qr.passed:
        await update.message.reply_text(
            '⚠️ فشل فحص الجودة بعد التعديل — راجعناه مجانًا.')
        await ctx.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🚨 فشل جودة بعد تعديل `{order_id}`: "
                 f"{';'.join(c for c, _ in qr.issues[:5])}",
            parse_mode='Markdown')
        return ConversationHandler.END
    langs = ['ar', 'en'] if dd['lang'] == 'both' else [dd['lang']]
    for lg in langs:
        suffix = f'_{lg}' if dd['lang'] == 'both' else ''
        await update.message.reply_document(
            document=open(os.path.join(order_dir(order_id), f'cv{suffix}.pdf'), 'rb'),
            filename=f'CV_{order_id}{suffix}_edit.pdf')
        await update.message.reply_document(
            document=open(os.path.join(order_dir(order_id), f'cv{suffix}.docx'), 'rb'),
            filename=f'CV_{order_id}{suffix}_edit.docx')
    nd = db.get(order_id)
    await update.message.reply_text(
        f'✅ تم التعديل ({charge_kind}).\n'
        f"المتبقي: {nd.get('edits_free_left', 0)} مجاني / "
        f"{nd.get('edits_paid_left', 0)} مدفوع.")
    return ConversationHandler.END


async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('تم الإلغاء. أرسل /start للبدء من جديد.')
    return ConversationHandler.END


# ================= ADMIN PANEL (buttons only, server-side permission) =================
def _admin_kb():
    # CV ADMIN CENTER — organized groups
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('📊 نظرة عامة', callback_data='ac:dashboard')],
        [InlineKeyboardButton('📦 الطلبات', callback_data='ac:orders'),
         InlineKeyboardButton('💳 المدفوعات', callback_data='ac:payments')],
        [InlineKeyboardButton('💰 الأرباح', callback_data='ac:profits'),
         InlineKeyboardButton('⭐ التقييمات', callback_data='ac:ratings')],
        [InlineKeyboardButton('👥 المستخدمون', callback_data='ac:users'),
         InlineKeyboardButton('🎨 القوالب', callback_data='ac:templates')],
        [InlineKeyboardButton('📣 إذاعة', callback_data='ac:broadcast'),
         InlineKeyboardButton('📢 الاشتراك الإجباري', callback_data='ac:channels')],
        [InlineKeyboardButton('🎁 الدعوات', callback_data='ac:referrals'),
         InlineKeyboardButton('👋 الترحيب', callback_data='ac:welcome')],
        [InlineKeyboardButton('🧪 المختبر', callback_data='ac:lab'),
         InlineKeyboardButton('🤖 الذكاء الاصطناعي', callback_data='adm:ai')],
        [InlineKeyboardButton('📈 التقارير', callback_data='ac:reports'),
         InlineKeyboardButton('🛠️ الأخطاء', callback_data='ac:errors')],
        [InlineKeyboardButton('💾 النسخ الاحتياطي', callback_data='ac:backup'),
         InlineKeyboardButton('⚙️ الإعدادات', callback_data='ac:settings')],
    ])

def _ac_back_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('↩️ رجوع للرئيسية', callback_data='ac:dashboard')],
    ])


async def admin_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not check_admin(update.effective_user.id, ADMIN_ID):
        await (update.message.reply_text('⛔ للإدارة فقط.')
               if update.message else update.callback_query.answer(
                   '⛔ للإدارة فقط.', show_alert=True))
        # Log unauthorized access attempt
        try:
            db.audit(update.effective_user.id, 'admin_access_denied', '')
        except Exception:
            pass
        return
    import admin_center
    admin_center.migrate_admin_center(db.DB_PATH)
    s = admin_center.get_dashboard_stats(db.DB_PATH)
    text = admin_center.format_dashboard(s)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(text, parse_mode='Markdown',
                                                       reply_markup=_admin_kb())
    else:
        await update.message.reply_text(text, parse_mode='Markdown',
                                        reply_markup=_admin_kb())




async def rate_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle user rating 1-10. One rating per order (update allowed)."""
    q = update.callback_query
    await q.answer()
    try:
        _, order_id, score = q.data.split(':')
        score = int(score)
        if not 1 <= score <= 10:
            return
    except (ValueError, IndexError):
        return
    user_id = q.from_user.id
    # Verify order belongs to user and was delivered
    d = db.get(order_id)
    if not d or d.get('user_id') != user_id:
        await q.message.reply_text('⚠️ هذا التقييم غير مرتبط بطلبك.')
        return
    if d.get('status') != 'delivered':
        await q.message.reply_text('⚠️ التقييم متاح بعد استلام السيرة فقط.')
        return
    import sqlite3
    conn = sqlite3.connect(db.DB_PATH)
    conn.execute(
        "INSERT INTO ratings (order_id, user_id, rating, updated_at) "
        "VALUES (?,?,?,datetime('now')) "
        "ON CONFLICT(order_id) DO UPDATE SET rating=excluded.rating, "
        "updated_at=datetime('now')",
        (order_id, user_id, score))
    conn.commit()
    conn.close()
    db.audit(user_id, 'rated', f'{order_id}:{score}')
    await q.message.reply_text(
        f'شكرًا! قيّمت السيرة بـ {score}/10. ⭐\nملاحظتك تساعدنا نحسّن.')


async def bc_compose_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Capture admin's broadcast message content."""
    if not ctx.user_data.get('bc_compose'):
        return  # not composing
    if not check_admin(update.effective_user.id, ADMIN_ID):
        return
    ctx.user_data.pop('bc_compose', None)
    msg = update.message
    import broadcast_sys

    content_type = None
    content_ref = None
    caption = msg.caption or ''

    if msg.text:
        content_type = 'text'
        content_ref = msg.text
    elif msg.photo:
        content_type = 'photo'
        content_ref = msg.photo[-1].file_id
    elif msg.video:
        content_type = 'video'
        content_ref = msg.video.file_id
    elif msg.document:
        content_type = 'document'
        content_ref = msg.document.file_id
    elif msg.voice:
        content_type = 'voice'
        content_ref = msg.voice.file_id
    elif msg.animation:
        content_type = 'animation'
        content_ref = msg.animation.file_id
    else:
        await msg.reply_text('⚠️ نوع الرسالة غير مدعوم للإذاعة.')
        return

    bid, target = broadcast_sys.create_broadcast(
        db.DB_PATH, update.effective_user.id,
        content_type, content_ref, caption)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton('👁️ معاينة', callback_data=f'bc_preview:{bid}')],
        [InlineKeyboardButton('▶️ تأكيد الإرسال',
                              callback_data=f'ac:bc_confirm:{bid}'),
         InlineKeyboardButton('❌ إلغاء',
                              callback_data=f'ac:bc_cancel:{bid}')],
    ])
    await msg.reply_text(
        f'📣 *إذاعة #{bid} جاهزة*\n\n'
        f'النوع: {content_type}\n'
        f'المستلمون: {target}\n\n'
        f'راجع ثم أكّد الإرسال.',
        parse_mode='Markdown', reply_markup=kb)


async def ch_add_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Capture channel input from admin."""
    if not ctx.user_data.get('ch_add'):
        return
    if not check_admin(update.effective_user.id, ADMIN_ID):
        return
    ctx.user_data.pop('ch_add', None)
    import force_sub
    parsed = force_sub.parse_channel_input(update.message.text or '')
    if not parsed:
        await update.message.reply_text(
            '⚠️ صيغة غير صالحة. أرسل معرف رقمي أو @username أو رابط t.me')
        return
    # Verify channel accessible
    chat_id = parsed['channel_id'] or parsed['username']
    try:
        chat = await ctx.bot.get_chat(chat_id=chat_id)
        title = chat.title or ''
        invite = ''
        # Check bot can check membership
        try:
            await ctx.bot.get_chat_member(chat_id=chat_id,
                                          user_id=update.effective_user.id)
            can_check = True
        except Exception:
            can_check = False
        if not can_check:
            await update.message.reply_text(
                '⚠️ البوت لا يستطيع فحص العضوية. اجعله مشرفًا في القناة أولًا.')
                # Don't add unverifiable channel
            return
    except Exception as e:
        await update.message.reply_text(
            f'⚠️ تعذر الوصول للقناة: {str(e)[:100]}')
        return
    ok, msg = force_sub.add_channel(
        db.DB_PATH, parsed['channel_id'], parsed['username'], title, invite)
    if ok:
        db.audit(update.effective_user.id, 'channel_added', chat_id)
        await update.message.reply_text(f'✅ أُضيفت القناة: {title or chat_id}')
    else:
        await update.message.reply_text('⚠️ القناة موجودة مسبقًا.')


async def sub_check_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Re-verify subscription after user taps check."""
    q = update.callback_query
    await q.answer()
    import force_sub
    # Skip for admin
    if check_admin(q.from_user.id, ADMIN_ID):
        await q.message.reply_text('✅ أنت مشرف، لا حاجة للاشتراك.')
        return
    ok, missing = await force_sub.check_membership(
        ctx.bot, db.DB_PATH, q.from_user.id)
    if ok:
        await q.message.reply_text('✅ تم التحقق! أرسل /start للمتابعة.')
    else:
        names = ', '.join(ch.get('title') or ch.get('username', '?')
                          for ch in missing)
        await q.message.reply_text(
            f'⚠️ ما زلت غير مشترك في: {names}\nاشترك ثم أعد التحقق.')


async def ref_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """User referral dashboard."""
    q = update.callback_query
    await q.answer()
    user_id = q.from_user.id
    action = q.data.split(':')[1] if ':' in q.data else ''

    import referral_sys
    # Get bot username for deep link
    try:
        me = await ctx.bot.get_me()
        bot_username = me.username
    except Exception:
        bot_username = 'Iqcvmakerbot'

    if action == 'dashboard':
        stats = referral_sys.get_referral_stats(db.DB_PATH, user_id)
        link = f'https://t.me/{bot_username}?start=ref_{user_id}'
        status_txt = {
            'locked': '🔒 لم تُفتح بعد',
            'available': '🎁 متاحة! اضغط لاستخدامها',
            'in_use': '⏳ قيد الاستخدام',
            'used': '✅ مستخدمة',
        }.get(stats['status'], stats['status'])
        text = (
            f"🎁 *ادعُ أصدقاءك واحصل على سيرة مجانية*\n\n"
            f"رابط دعوتك الخاص:\n`{link}`\n\n"
            f"📊 *تقدمك:*\n"
            f"• الدعوات الناجحة: {stats['count']} من 10\n"
            f"• المتبقي: {stats['remaining']}\n"
            f"• حالة المكافأة: {status_txt}"
        )
        kb = [[InlineKeyboardButton('🔗 نسخ الرابط', url=link)]]
        if stats['status'] == 'available':
            kb.append([InlineKeyboardButton(
                '🎁 إنشاء سيرتي المجانية',
                callback_data='ref:use_reward')])
        kb.append([InlineKeyboardButton('↩️ رجوع', callback_data='back:start')])
        await q.message.reply_text(text, parse_mode='Markdown',
                                   reply_markup=InlineKeyboardMarkup(kb))

    elif action == 'use_reward':
        stats = referral_sys.get_referral_stats(db.DB_PATH, user_id)
        if stats['status'] != 'available':
            await q.message.reply_text('⚠️ المكافأة غير متاحة حاليًا.')
            return
        # Create free order (reuse existing order creation)
        import uuid
        order_id = f"FREE-{uuid.uuid4().hex[:6].upper()}"
        db.create_order(order_id, user_id, '')
        db.update(order_id, is_free_reward=1)
        # Mark reward in use
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        conn.execute(
            "UPDATE rewards SET reward_status='in_use', reward_order_id=? "
            "WHERE user_id=?", (order_id, user_id))
        conn.commit()
        conn.close()
        ctx.user_data['order_id'] = order_id
        ctx.user_data['is_free'] = True
        await q.message.reply_text(
            f'🎁 *مبروك!* بدأنا طلب سيرتك المجانية ({order_id})\n\n'
            f'أرسل اسمك الكامل للبدء.',
            parse_mode='Markdown')
        return NAME  # start collection flow


async def welcome_edit_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.user_data.get('welcome_edit'):
        return
    if not check_admin(update.effective_user.id, ADMIN_ID):
        return
    ctx.user_data.pop('welcome_edit', None)
    import welcome_sys
    ok, msg = welcome_sys.set_welcome(
        db.DB_PATH, update.message.text or '', update.effective_user.id)
    if ok:
        db.audit(update.effective_user.id, 'welcome_updated', '')
        await update.message.reply_text('✅ حُفظت رسالة الترحيب الجديدة.')
    else:
        await update.message.reply_text(f'⚠️ فشل الحفظ: {msg}')


async def user_search_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.user_data.get('user_search'):
        return
    if not check_admin(update.effective_user.id, ADMIN_ID):
        return
    ctx.user_data.pop('user_search', None)
    query = (update.message.text or '').strip().lstrip('@')
    import sqlite3
    conn = sqlite3.connect(db.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        # Try as ID
        row = conn.execute(
            "SELECT * FROM users WHERE user_id=? OR username LIKE ?",
            (query, f'%{query}%')).fetchone()
    except Exception:
        row = None
    conn.close()
    if not row:
        await update.message.reply_text('⚠️ لم يُعثر على المستخدم.')
        return
    uid = row['user_id']
    # Get stats
    conn = sqlite3.connect(db.DB_PATH)
    orders = conn.execute(
        "SELECT COUNT(*) FROM orders WHERE user_id=?", (uid,)).fetchone()[0]
    try:
        refs = conn.execute(
            "SELECT COUNT(*) FROM referrals WHERE referrer_id=?",
            (uid,)).fetchone()[0]
    except Exception:
        refs = 0
    conn.close()
    text = (f"👤 *المستخدم*\n\n"
            f"ID: `{uid}`\n"
            f"Username: @{row['username'] or '?'}\n"
            f"الطلبات: {orders}\n"
            f"الدعوات: {refs}")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton('📦 طلباته',
                              callback_data=f'ac:user_orders:{uid}'),
         InlineKeyboardButton('🚫 حظر', callback_data=f'ac:user_ban:{uid}')],
        [InlineKeyboardButton('↩️ رجوع', callback_data='ac:users')],
    ])
    await update.message.reply_text(text, parse_mode='Markdown',
                                    reply_markup=kb)

async def ac_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """CV Admin Center callback handler. All actions check admin."""
    q = update.callback_query
    if not check_admin(q.from_user.id, ADMIN_ID):
        await q.answer('⛔ للإدارة فقط.', show_alert=True)
        return
    await q.answer()
    action = q.data.split(':', 1)[1] if ':' in q.data else ''
    import admin_center

    async def edit(text, kb=None):
        try:
            await q.message.edit_text(text, parse_mode='Markdown',
                                      reply_markup=kb or _ac_back_kb())
        except Exception:
            await q.message.reply_text(text, parse_mode='Markdown',
                                       reply_markup=kb or _ac_back_kb())

    if action == 'dashboard':
        s = admin_center.get_dashboard_stats(db.DB_PATH)
        await edit(admin_center.format_dashboard(s), _admin_kb())

    elif action == 'orders':
        s = admin_center.get_dashboard_stats(db.DB_PATH)
        text = (f"📦 *إدارة الطلبات*\n\n"
                f"الإجمالي: {s['orders_total']}\n"
                f"🆕 جديدة: {s['orders_new']}\n"
                f"⏳ قيد المعالجة: {s['orders_processing']}\n"
                f"⚠️ عالقة: {s['orders_stuck']}\n"
                f"✅ مسلّمة: {s['orders_delivered']}")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton('🆕 الجديدة', callback_data='ac:orders_new'),
             InlineKeyboardButton('⏳ قيد المعالجة', callback_data='ac:orders_proc')],
            [InlineKeyboardButton('⚠️ العالقة', callback_data='ac:orders_stuck'),
             InlineKeyboardButton('✅ المسلّمة', callback_data='ac:orders_done')],
            [InlineKeyboardButton('🔍 بحث', callback_data='adm:find')],
            [InlineKeyboardButton('↩️ رجوع', callback_data='ac:dashboard')],
        ])
        await edit(text, kb)

    elif action in ('orders_new', 'orders_proc', 'orders_stuck', 'orders_done'):
        status_map = {
            'orders_new': ('collecting', 'template', 'preview'),
            'orders_proc': ('generating', 'under_review'),
            'orders_stuck': ('quality_failed', 'regenerating'),
            'orders_done': ('delivered',),
        }
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        conn.row_factory = sqlite3.Row
        placeholders = ','.join('?' * len(status_map[action]))
        rows = conn.execute(
            f"SELECT order_id, user_id, status, payment_status, created_at "
            f"FROM orders WHERE status IN ({placeholders}) "
            f"ORDER BY created_at DESC LIMIT 10",
            status_map[action]).fetchall()
        conn.close()
        if not rows:
            await edit('لا توجد طلبات في هذه الفئة.')
            return
        lines = [f"*الطلبات ({len(rows)}):*\n"]
        for r in rows:
            lines.append(f"• `{r['order_id']}` — {r['status']} / {r['payment_status']}")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton('↩️ رجوع', callback_data='ac:orders')],
        ])
        await edit('\n'.join(lines), kb)

    elif action == 'payments':
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        pend = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE payment_status='under_review'"
            ).fetchone()[0]
        appr = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE payment_status='approved'"
            ).fetchone()[0]
        rej = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE payment_status='rejected'"
            ).fetchone()[0]
        conn.close()
        text = (f"💳 *مركز المدفوعات*\n\n"
                f"⏳ بانتظار المراجعة: {pend}\n"
                f"✅ مقبولة: {appr}\n"
                f"❌ مرفوضة: {rej}\n\n"
                f"⚠️ الموافقة النهائية بيد الإدارة دائمًا.")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton('⏳ بانتظار المراجعة', callback_data='adm:pending')],
            [InlineKeyboardButton('↩️ رجوع', callback_data='ac:dashboard')],
        ])
        await edit(text, kb)

    elif action == 'profits':
        s = admin_center.get_dashboard_stats(db.DB_PATH)
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        # Today
        today_rev = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE payment_status='approved' "
            "AND date(created_at)=date('now') "
            "AND (is_free_reward IS NULL OR is_free_reward=0)").fetchone()[0] * 5000
        # Week
        week_rev = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE payment_status='approved' "
            "AND datetime(created_at) >= datetime('now','-7 days') "
            "AND (is_free_reward IS NULL OR is_free_reward=0)").fetchone()[0] * 5000
        # Month
        month_rev = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE payment_status='approved' "
            "AND datetime(created_at) >= datetime('now','-30 days') "
            "AND (is_free_reward IS NULL OR is_free_reward=0)").fetchone()[0] * 5000
        costs = s.get('costs_iqd', 0)
        conn.close()
        text = (f"💰 *الأرباح والإيرادات*\n\n"
                f"💵 إجمالي الإيرادات المؤكدة: {s['revenue_iqd']:,} د.ع\n"
                f"💸 التكاليف المسجلة: {costs:,} د.ع\n"
                f"📈 صافي الربح: {s.get('net_profit_iqd', 0):,} د.ع\n\n"
                f"🗓️ اليوم: {today_rev:,} د.ع\n"
                f"📅 الأسبوع: {week_rev:,} د.ع\n"
                f"🗓️ الشهر: {month_rev:,} د.ع\n\n"
                f"_المبالغ المعلقة والمرفوضة غير محسوبة._")
        await edit(text)

    elif action == 'ratings':
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            r = conn.execute(
                "SELECT AVG(rating), COUNT(*), MIN(rating), MAX(rating) "
                "FROM ratings").fetchone()
            if r[1] == 0:
                await edit('⭐ لا توجد تقييمات بعد.')
            else:
                # Distribution
                dist = conn.execute(
                    "SELECT rating, COUNT(*) FROM ratings GROUP BY rating "
                    "ORDER BY rating").fetchall()
                lines = [f"⭐ *تقييمات السير الذاتية*\n",
                         f"المتوسط: {r[0]:.1f}/10",
                         f"العدد: {r[1]}",
                         f"الأدنى: {r[2]} | الأعلى: {r[3]}", "",
                         "*التوزيع:*"]
                for d in dist:
                    lines.append(f"{d[0]}: {'█' * d[1]} ({d[1]})")
                await edit('\n'.join(lines))
        except Exception as e:
            await edit(f'⚠️ خطأ: {e}')
        conn.close()

    elif action == 'users':
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        # Recent users
        rows = conn.execute(
            "SELECT user_id, username, created_at FROM users "
            "ORDER BY created_at DESC LIMIT 5").fetchall()
        conn.close()
        lines = [f"👥 *المستخدمون ({total})*\n", "*الأحدث:*"]
        for r in rows:
            lines.append(f"• `{r[0]}` @{r[1] or '?'}")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton('🔍 بحث عن مستخدم', callback_data='ac:user_search')],
            [InlineKeyboardButton('↩️ رجوع', callback_data='ac:dashboard')],
        ])
        await edit('\n'.join(lines), kb)

    elif action == 'user_search':
        ctx.user_data['user_search'] = True
        await edit('🔍 أرسل Telegram ID أو username للبحث.')

    elif action.startswith('user_orders:'):
        uid = action.split(':')[1]
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT order_id, status, payment_status FROM orders "
            "WHERE user_id=? ORDER BY created_at DESC LIMIT 10",
            (uid,)).fetchall()
        conn.close()
        if not rows:
            await edit('لا توجد طلبات.')
        else:
            lines = [f"*طلبات `{uid}`:*\n"]
            for r in rows:
                lines.append(f"• `{r['order_id']}`: {r['status']}")
            await edit('\n'.join(lines))

    elif action.startswith('user_ban:'):
        uid = action.split(':')[1]
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO banned_users (user_id, banned_at) "
                "VALUES (?, datetime('now'))", (uid,))
            conn.commit()
            db.audit(q.from_user.id, 'user_banned', str(uid))
            await edit(f'🚫 حُظر المستخدم `{uid}`.')
        except Exception as e:
            await edit(f'⚠️ خطأ: {e}')
        conn.close()

    elif action == 'templates':
        import templates_registry as tr
        lines = ["🎨 *القوالب*\n"]
        for t in tr.TEMPLATES:
            status = '✅' if t.get('ready') else '⏸️'
            lines.append(f"{status} `{t['id']}` — {t.get('name_ar', '')}")
        await edit('\n'.join(lines))

    elif action == 'referrals':
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        try:
            total_refs = conn.execute(
                "SELECT COUNT(*) FROM referrals").fetchone()[0]
            total_rewards = conn.execute(
                "SELECT COUNT(*) FROM rewards").fetchone()[0]
            avail = conn.execute(
                "SELECT COUNT(*) FROM rewards WHERE reward_status='available'"
                ).fetchone()[0]
            used = conn.execute(
                "SELECT COUNT(*) FROM rewards WHERE reward_status='used'"
                ).fetchone()[0]
        except Exception:
            total_refs = total_rewards = avail = used = 0
        conn.close()
        text = (f"🎁 *الدعوات والمكافآت*\n\n"
                f"إجمالي الدعوات: {total_refs}\n"
                f"المكافآت: {total_rewards} (متاحة: {avail} | مستخدمة: {used})")
        await edit(text)

    elif action == 'channels':
        import force_sub
        channels = force_sub.get_active_channels(db.DB_PATH)
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        try:
            total = conn.execute(
                "SELECT COUNT(*) FROM force_channels").fetchone()[0]
        except Exception:
            total = 0
        conn.close()
        text = (f"📢 *الاشتراك الإجباري*\n\n"
                f"القنوات النشطة: {len(channels)} / {total}")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton('➕ إضافة قناة', callback_data='ac:ch_add'),
             InlineKeyboardButton('📋 القنوات', callback_data='ac:ch_list')],
            [InlineKeyboardButton('↩️ رجوع', callback_data='ac:dashboard')],
        ])
        await edit(text, kb)

    elif action == 'ch_add':
        ctx.user_data['ch_add'] = True
        await edit("📝 أرسل معرف القناة أو @username أو رابط t.me")

    elif action == 'ch_list':
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT id, channel_id, username, title, active "
                "FROM force_channels").fetchall()
        except Exception:
            rows = []
        conn.close()
        if not rows:
            await edit('لا توجد قنوات.')
        else:
            lines = ["📋 *القنوات:*\n"]
            kb_rows = []
            for r in rows:
                status = '🟢' if r['active'] else '⏸️'
                name = r['username'] or r['channel_id']
                lines.append(f"{status} `{r['id']}`: {name}")
                kb_rows.append([
                    InlineKeyboardButton(
                        f"🗑️ حذف {r['id']}",
                        callback_data=f"ac:ch_del:{r['id']}"),
                ])
            kb_rows.append([InlineKeyboardButton(
                '↩️ رجوع', callback_data='ac:channels')])
            await edit('\n'.join(lines), InlineKeyboardMarkup(kb_rows))

    elif action.startswith('ch_del:'):
        cid = int(action.split(':')[1])
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        conn.execute("DELETE FROM force_channels WHERE id=?", (cid,))
        conn.commit()
        conn.close()
        db.audit(q.from_user.id, 'channel_deleted', str(cid))
        await edit(f'🗑️ حُذفت القناة {cid}.')

    elif action == 'welcome':
        import welcome_sys
        current = welcome_sys.get_welcome(db.DB_PATH)
        preview = current[:200] + '...' if len(current) > 200 else current
        text = f"👋 *رسالة الترحيب*\n\n{preview}"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton('👁️ عرض كاملة', callback_data='ac:welcome_view'),
             InlineKeyboardButton('✏️ تعديل', callback_data='ac:welcome_edit')],
            [InlineKeyboardButton('🔄 استعادة الافتراضية',
                                  callback_data='ac:welcome_reset')],
            [InlineKeyboardButton('↩️ رجوع', callback_data='ac:dashboard')],
        ])
        await edit(text, kb)

    elif action == 'welcome_view':
        import welcome_sys
        current = welcome_sys.get_welcome(db.DB_PATH)
        await q.message.reply_text(f"👋 *الرسالة الحالية:*\n\n{current}",
                                   parse_mode='Markdown')

    elif action == 'welcome_edit':
        ctx.user_data['welcome_edit'] = True
        await edit("✏️ أرسل رسالة الترحيب الجديدة.\n"
                   "يمكنك استخدام {user_name} و {bot_name}.")

    elif action == 'welcome_reset':
        import welcome_sys, sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        conn.execute("DELETE FROM settings WHERE key='welcome_message'")
        conn.commit()
        conn.close()
        db.audit(q.from_user.id, 'welcome_reset', '')
        await edit('🔄 استُعيدت الرسالة الافتراضية.')

    elif action == 'lab':
        text = ("🧪 *مختبر السير الذاتية*\n\n"
                "منظومة التقييم: `ai/eval_framework.py`\n"
                "القوالب المختبرة: 3 (96.2/100 متوسط)\n"
                "الشخصيات التجريبية: 12")
        await edit(text)

    elif action == 'reports':
        text = ("📈 *التقارير*\n\nاختر الفترة:")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton('📅 اليوم', callback_data='ac:rep_day'),
             InlineKeyboardButton('📅 الأسبوع', callback_data='ac:rep_week')],
            [InlineKeyboardButton('📅 الشهر', callback_data='ac:rep_month')],
            [InlineKeyboardButton('↩️ رجوع', callback_data='ac:dashboard')],
        ])
        await edit(text, kb)

    elif action in ('rep_day', 'rep_week', 'rep_month'):
        days = {'rep_day': 1, 'rep_week': 7, 'rep_month': 30}[action]
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        orders = conn.execute(
            f"SELECT COUNT(*) FROM orders WHERE datetime(created_at) >= "
            f"datetime('now','-{days} days')").fetchone()[0]
        delivered = conn.execute(
            f"SELECT COUNT(*) FROM orders WHERE status='delivered' AND "
            f"datetime(created_at) >= datetime('now','-{days} days')").fetchone()[0]
        revenue = conn.execute(
            f"SELECT COUNT(*) FROM orders WHERE payment_status='approved' AND "
            f"datetime(created_at) >= datetime('now','-{days} days') AND "
            f"(is_free_reward IS NULL OR is_free_reward=0)").fetchone()[0] * 5000
        conn.close()
        name = {'rep_day': 'اليوم', 'rep_week': 'الأسبوع', 'rep_month': 'الشهر'}[action]
        text = (f"📈 *تقرير {name}*\n\n"
                f"الطلبات: {orders}\n"
                f"المسلّمة: {delivered}\n"
                f"الإيرادات: {revenue:,} د.ع")
        await edit(text)

    elif action == 'errors':
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        # Recent audit errors
        try:
            rows = conn.execute(
                "SELECT action, details, created_at FROM audit_log "
                "WHERE action LIKE '%error%' OR action LIKE '%fail%' "
                "ORDER BY created_at DESC LIMIT 10").fetchall()
        except Exception:
            rows = []
        conn.close()
        if not rows:
            await edit('✅ لا توجد أخطاء مسجلة حديثًا.')
        else:
            lines = ["🛠️ *الأخطاء الأخيرة:*\n"]
            for r in rows:
                lines.append(f"• {r[0]}: {(r[1] or '')[:50]}")
            await edit('\n'.join(lines))

    elif action == 'backup':
        import os, tarfile, datetime
        try:
            ts = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
            bpath = f"/data/data/com.termux/files/home/tmp/cvbot-backup-{ts}.tar.gz"
            proj = '/data/data/com.termux/files/home/bots/cvbot'
            with tarfile.open(bpath, 'w:gz') as tar:
                for item in ['bot.py', 'db.py', 'cvbot.db', 'admin_center.py']:
                    fp = os.path.join(proj, item)
                    if os.path.exists(fp) and '.env' not in fp:
                        tar.add(fp, arcname=item)
            # Verify
            with tarfile.open(bpath, 'r:gz') as tar:
                members = tar.getnames()
            size = os.path.getsize(bpath)
            db.audit(q.from_user.id, 'backup_created', f'{len(members)} files')
            text = (f"💾 *تم إنشاء نسخة احتياطية*\n\n"
                    f"الملفات: {len(members)}\n"
                    f"الحجم: {size:,} بايت\n"
                    f"المسار: `{bpath}`")
        except Exception as e:
            text = f'⚠️ فشل النسخ: {str(e)[:100]}'
        await edit(text)

    elif action == 'settings':
        text = ("⚙️ *الإعدادات*\n\n"
                "السعر: 5,000 د.ع (ثابت)\n"
                "الدفع: يدوي عبر كي كارد\n"
                "الإصدار: CV Bot v2")
        await edit(text)

    elif action == 'broadcast':
        text = ("📣 *الإذاعة*\n\n"
                "أرسل الرسالة (نص/صورة/فيديو/ملف) إلى البوت هنا، "
                "ثم اضغط تأكيد للإرسال الجماعي.")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton('📣 إذاعة جديدة', callback_data='ac:bc_new'),
             InlineKeyboardButton('📊 السجل', callback_data='ac:bc_log')],
            [InlineKeyboardButton('↩️ رجوع', callback_data='ac:dashboard')],
        ])
        await edit(text, kb)

    elif action == 'bc_new':
        ctx.user_data['bc_compose'] = True
        await edit("📝 أرسل الآن الرسالة التي تريد إذاعتها "
                   "(نص، صورة، فيديو، أو ملف).")

    elif action == 'bc_log':
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT id, status, target_count, sent_count, failed_count, "
                "created_at FROM broadcasts ORDER BY id DESC LIMIT 10").fetchall()
        except Exception:
            rows = []
        conn.close()
        if not rows:
            await edit('📊 لا توجد إذاعات سابقة.')
        else:
            lines = ["📊 *سجل الإذاعات:*\n"]
            for r in rows:
                lines.append(
                    f"• #{r['id']}: {r['status']} — "
                    f"✅{r['sent_count']}/❌{r['failed_count']}/{r['target_count']}")
            await edit('\n'.join(lines))

    elif action.startswith('bc_confirm:'):
        bid = int(action.split(':')[1])
        await edit(f"⏳ جاري الإرسال للإذاعة #{bid}...")
        import broadcast_sys
        result = await broadcast_sys.send_broadcast(ctx.bot, db.DB_PATH, bid)
        if result:
            await q.message.reply_text(
                f"✅ اكتملت الإذاعة #{bid}\n"
                f"✅ ناجحة: {result['sent']}\n"
                f"❌ فاشلة: {result['failed']}",
                reply_markup=_ac_back_kb())
        else:
            await q.message.reply_text('⚠️ تعذر إرسال الإذاعة.',
                                       reply_markup=_ac_back_kb())

    elif action.startswith('bc_cancel:'):
        bid = int(action.split(':')[1])
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        conn.execute(
            "UPDATE broadcasts SET status='cancelled' WHERE id=?", (bid,))
        conn.commit()
        conn.close()
        await edit(f'❌ أُلغيت الإذاعة #{bid}.')

    else:
        await edit('🚧 هذا القسم قيد التطوير.')


async def admin_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not check_admin(q.from_user.id, ADMIN_ID):
        await q.answer('⛔ للإدارة فقط.', show_alert=True)
        return
    await q.answer()
    action = q.data.split(':')[1]

    if action == 'stats':
        s = db.stats()
        await q.message.reply_text(
            f'📊 *نظرة عامة*\n\nطلبات: {s["orders_total"]}\n'
            f"مُسلّمة: {s['delivered']}\nمدفوعات معلقة: {s['pending_pay']}\n"
            f"مستخدمون: {s['users']}",
            parse_mode='Markdown', reply_markup=_admin_kb())

    elif action == 'pending':
        pend = db.pending_payments()
        if not pend:
            await q.message.reply_text('✅ لا توجد مدفوعات معلقة.',
                                       reply_markup=_admin_kb())
            return
        for p in pend[:5]:
            kb = [[InlineKeyboardButton('✅ موافقة',
                                        callback_data=f"adm_pay:approve:{p['order_id']}"),
                   InlineKeyboardButton('❌ رفض',
                                        callback_data=f"adm_pay:reject:{p['order_id']}")]]
            await q.message.reply_text(
                f"🧾 `{p['order_id']}` — {p.get('full_name')} — {p.get('phone')}",
                parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif action == 'stuck':
        stuck = db.stuck_orders()
        if not stuck:
            await q.message.reply_text('✅ لا توجد طلبات عالقة.',
                                       reply_markup=_admin_kb())
            return
        lines = []
        for d, why in stuck[:10]:
            lines.append(
                f"• `{d['order_id']}` — {why}\n"
                f"  {d.get('full_name') or '—'} | {d.get('phone') or '—'} |"
                f" {d.get('updated_at','')[:16]}")
        await q.message.reply_text(
            '⏳ *طلبات عالقة:*\n\n' + '\n'.join(lines),
            parse_mode='Markdown', reply_markup=_admin_kb())

    elif action == 'find':
        ctx.user_data['admin_find'] = True
        await q.message.reply_text(
            '🔍 أرسل *رقم الطلب* (مثال: `CV-123456`):',
            parse_mode='Markdown')

    elif action == 'templates':
        rows = []
        for t in db.all_templates():
            mark = '✅' if t['ready'] else '❌'
            rows.append([InlineKeyboardButton(
                f"{mark} {t['name_ar']}",
                callback_data=f"adm:tmpl:{t['id']}")])
        rows.append([InlineKeyboardButton('🔙 رجوع', callback_data='adm:back')])
        await q.message.reply_text('🎨 *القوالب* — اضغط للتبديل:',
                                   parse_mode='Markdown',
                                   reply_markup=InlineKeyboardMarkup(rows))

    elif action == 'tmpl':
        tid = q.data.split(':')[2]
        t = get_template(tid)
        if t:
            db.set_template_ready(tid, not t['ready'])
            db.audit(q.from_user.id, 'template_toggle',
                     f"{tid} -> {'on' if not t['ready'] else 'off'}")
            await q.answer(f"تم {'تفعيل' if not t['ready'] else 'تعطيل'} {t['name_ar']}")
        # refresh list
        q.data = 'adm:templates'
        await admin_cb(update, ctx)

    elif action == 'ai':
        await _admin_ai_menu(q, ctx)

    elif action == 'audit':
        logs = db.recent_audit(10)
        txt = '📝 *سجل العمليات:*\n\n' + '\n'.join(
            f"• {l['created_at'][:16]} — {l['action']} — {l['detail'][:40]}"
            for l in logs) or 'فارغ'
        await q.message.reply_text(txt, parse_mode='Markdown',
                                   reply_markup=_admin_kb())

    elif action == 'back':
        await admin_entry(update, ctx)


async def admin_find_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Standalone (group=-1): consumes one text message when the admin pressed
    '🔍 بحث عن طلب' and shows the order's state."""
    if not ctx.user_data.get('admin_find'):
        return  # not ours — let other handlers process it
    if not check_admin(update.effective_user.id, ADMIN_ID):
        return
    ctx.user_data.pop('admin_find', None)
    oid = (update.message.text or '').strip().upper()
    d = db.get(oid)
    if not d:
        await update.message.reply_text(f'⚠️ لا يوجد طلب برقم `{oid}`.',
                                        parse_mode='Markdown')
        raise ApplicationHandlerStop
    st_ar = {'collecting': 'قيد الإنشاء', 'template': 'اختيار القالب',
             'preview': 'معاينة', 'awaiting_payment': 'بانتظار الدفع',
             'payment_review': 'مراجعة الدفع', 'generating': 'قيد التوليد',
             'quality_check': 'فحص الجودة', 'quality_failed': 'فشل التوليد',
             'regenerating': 'إعادة توليد', 'ready': 'جاهز',
             'delivered': 'تم التسليم', 'rejected': 'مرفوض',
             'closed': 'مغلق', 'cancelled': 'ملغى'}
    pay_ar = {'unpaid': 'غير مدفوع', 'under_review': 'قيد المراجعة',
              'awaiting_receipt': 'بانتظار إيصال', 'approved': 'مقبول',
              'rejected': 'مرفوض'}
    lines = [
        f'🔍 *الطلب `{oid}`*', '',
        f"📌 الحالة: {st_ar.get(d.get('status'), d.get('status'))}",
        f"💳 الدفع: {pay_ar.get(d.get('payment_status'), d.get('payment_status'))}",
        f"👤 المستخدم: {d.get('full_name') or '—'}"
        f" (@{d.get('username') or '—'}) — `{d.get('user_id')}`",
        f"📞 الهاتف: {d.get('phone') or '—'}",
        f"📅 أُنشئ: {d.get('created_at') or '—'}",
        f"🔄 حُدّث: {d.get('updated_at') or '—'}",
    ]
    if d.get('approved_at'):
        lines.append(f"✅ اعتُمد: {d['approved_at']} بواسطة `{d.get('approved_by')}`")
    if d.get('payment_status') == 'rejected':
        lines.append(f"❌ سبب الرفض: {d.get('reject_reason') or '—'}")
        lines.append(f"🔄 محاولات إعادة الرفع: {d.get('reupload_count') or 0}/{REUPLOAD_MAX}")
    if d.get('quality_status'):
        lines.append(f"🧪 الجودة: {d.get('quality_status')}")
    await update.message.reply_text('\n'.join(lines), parse_mode='Markdown',
                                    reply_markup=_admin_kb())
    raise ApplicationHandlerStop


async def _admin_ai_menu(q, ctx):
    key_row = db.get_active_key('openrouter')
    model = db.get_setting('openrouter_model', OpenRouterProvider.DEFAULT_MODEL)
    key_status = f'مُدخل ✅ ({mask_key("xxxx" + (key_row["key_suffix"] or ""))})' \
        if key_row else 'مفقود ⚠️ — المحرك يعمل بالوضع القاعدي'
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton('🆓 موديلات OpenRouter المجانية',
                              callback_data='adm:ai_models:0')],
        [InlineKeyboardButton('🔑 إدخال/تحديث المفتاح',
                              callback_data='adm:ai_key')],
        [InlineKeyboardButton('🔙 رجوع', callback_data='adm:back')],
    ])
    await q.message.reply_text(
        f'🤖 *الذكاء الاصطناعي*\n\nالمفتاح: {key_status}\nالموديل الحالي:\n`{model}`',
        parse_mode='Markdown', reply_markup=kb)


async def admin_ai_models(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not check_admin(q.from_user.id, ADMIN_ID):
        await q.answer('⛔ للإدارة فقط.', show_alert=True)
        return
    offset = int(q.data.split(':')[2])
    if offset == 0 or 'or_models_cache' not in ctx.user_data:
        await q.answer('جاري الجلب من OpenRouter...')
        key_row = db.get_active_key('openrouter')
        api_key = decrypt_key(key_row['encrypted_key']) if key_row else None
        try:
            models = await fetch_openrouter_free_models(api_key=api_key)
        except Exception as e:
            await q.message.reply_text(f'❌ فشل الجلب: {e}',
                                       reply_markup=_admin_kb())
            return
        if not models:
            await q.message.reply_text('ماكو موديلات مجانية حاليًا.',
                                       reply_markup=_admin_kb())
            return
        ctx.user_data['or_models_cache'] = models
    else:
        await q.answer()
    models = ctx.user_data['or_models_cache']
    current = db.get_setting('openrouter_model', OpenRouterProvider.DEFAULT_MODEL)
    page = models[offset:offset + AI_PAGE_SIZE]
    rows = []
    for i, m in enumerate(page, start=offset):
        mark = '✅ ' if m['id'] == current else ''
        rows.append([InlineKeyboardButton(f"{mark}{m['name'][:42]}",
                                          callback_data=f'adm:ai_pick:{i}')])
    nav = []
    if offset > 0:
        nav.append(InlineKeyboardButton('⬅️ السابق',
                                        callback_data=f'adm:ai_models:{max(0, offset - AI_PAGE_SIZE)}'))
    if offset + AI_PAGE_SIZE < len(models):
        nav.append(InlineKeyboardButton('التالي ➡️',
                                        callback_data=f'adm:ai_models:{offset + AI_PAGE_SIZE}'))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton('🔄 تحديث القائمة', callback_data='adm:ai_models:0')])
    rows.append([InlineKeyboardButton('🔙 رجوع', callback_data='adm:ai')])
    await q.message.reply_text(
        f'🆓 *موديلات OpenRouter المجانية* ({len(models)})\nالحالي: `{current}`',
        parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(rows))


async def admin_ai_pick(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not check_admin(q.from_user.id, ADMIN_ID):
        await q.answer('⛔ للإدارة فقط.', show_alert=True)
        return
    idx = int(q.data.split(':')[2])
    models = ctx.user_data.get('or_models_cache', [])
    if idx >= len(models):
        await q.answer('انتهت صلاحية القائمة — حدّثها.', show_alert=True)
        return
    m = models[idx]
    db.set_setting('openrouter_model', m['id'])
    db.audit(q.from_user.id, 'changed_openrouter_model', m['id'])
    await q.answer('✅ تم الحفظ')
    await q.message.reply_text(f"✅ الموديل الجديد:\n{m['name']}\n(`{m['id']}`)",
                               parse_mode='Markdown', reply_markup=_admin_kb())


async def admin_ai_key_prompt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not check_admin(q.from_user.id, ADMIN_ID):
        await q.answer('⛔ للإدارة فقط.', show_alert=True)
        return ConversationHandler.END
    await q.answer()
    await q.message.reply_text(
        '🔑 أرسل مفتاح OpenRouter الجديد (يُحفظ مشفرًا ويُختبر فورًا).\n'
        'سيُحذف من المحادثة بعد الحفظ.',
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton('🔙 إلغاء', callback_data='adm:ai')]]))
    return ADMIN_AI_KEY


async def admin_ai_key_save(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.strip()
    try:
        await update.message.delete()
    except Exception:
        pass
    if not raw.startswith('sk-or-'):
        await update.message.reply_text('⚠️ المفتاح يبدو غير صالح (يجب أن يبدأ بـ sk-or-).')
        return ConversationHandler.END
    enc = encrypt_key(raw)
    db.add_api_key('openrouter', enc, raw[-4:])
    # test connection
    try:
        models = await fetch_openrouter_free_models(api_key=raw)
        status = f'✅ يعمل — {len(models)} موديل مجاني متاح'
    except Exception as e:
        status = f'⚠️ حُفظ لكن فشل الاختبار: {e}'
    db.audit(update.effective_user.id, 'openrouter_key_updated',
             f'suffix={raw[-4:]}')
    await update.message.reply_text(f'🔑 تم حفظ المفتاح.\n{status}',
                                    reply_markup=_admin_kb())
    return ConversationHandler.END


# ================= new features: dispatch wrappers =================
async def _menu_dispatch(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Route new main-menu buttons into their conversations."""
    q = update.callback_query
    data = q.data
    if data == 'intv:start':
        return await feat.intv_entry(update, ctx, get_engine)
    if data == 'import:old':
        return await feat.import_entry(update, ctx)
    if data == 'mem:open':
        return await feat.memory_menu(update, ctx)
    if data == 'share:open':
        me = await ctx.bot.get_me()
        await feat.share_menu(update, ctx, me.username or 'cvbot')
        return ConversationHandler.END
    await q.answer()
    return ConversationHandler.END



# ---- feature state wrappers (merged into main conv) ----
async def _intv_job_cb(u, c):
    return await feat.intv_job(u, c, get_engine)
async def _intv_type_cb(u, c):
    return await feat.intv_type(u, c, get_engine)
async def _intv_diff_cb(u, c):
    return await feat.intv_diff(u, c, get_engine)
async def _intv_cb2(u, c):
    return await feat.intv_cb(u, c, get_engine)
async def _intv_answer_h(u, c):
    return await feat.intv_answer(u, c, get_engine)
async def _exp_pick_h(u, c):
    return await feat.exp_pick_cb(u, c, get_engine)


async def _mem_consent_dispatch(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    return await feat.memory_consent_cb(update, ctx)


def main():
    db.init()
    seed_templates()
    n_stuck = db.reset_stuck_generating()
    if n_stuck:
        log.warning('reset %d order(s) stuck in regenerating -> quality_failed', n_stuck)
    app = Application.builder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler('start', start),
                      CallbackQueryHandler(edit_start, pattern=r'^edit:')],
        states={
            LANG: [CallbackQueryHandler(pick_lang,
                                        pattern=r'^(new|lang:|resume:|adm:open)'),
                     CallbackQueryHandler(_menu_dispatch,
                                        pattern=r'^(intv:start|import:old|mem:open|share:open)$')],
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_name)],
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_phone)],
            EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_email),
                    CallbackQueryHandler(got_email, pattern=r'^skip:')],
            ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_address)],
            JOB_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_job_title)],
            TARGET_JOB: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_target_job),
                         CallbackQueryHandler(skip_target_job, pattern=r'^tjob:skip$')],
            SUMMARY: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_summary),
                      CallbackQueryHandler(skip_summary, pattern=r'^sum:skip$')],
            SUMMARY_REVIEW: [CallbackQueryHandler(summary_pick, pattern=r'^sum:')],
            EXP_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_exp_title)],
            EXP_COMPANY: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_exp_company)],
            EXP_PERIOD: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_exp_period)],
            EXP_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_exp_desc)],
            EXP_MORE: [CallbackQueryHandler(exp_more, pattern=r'^exp:')],
            EDUCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_education)],
            CERTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_certs),
                    CallbackQueryHandler(got_certs, pattern=r'^skip:')],
            SKILLS: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_skills)],
            LANGS_KNOWN: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_langs),
                          CallbackQueryHandler(got_langs, pattern=r'^skip:')],
            DESIGN: [CallbackQueryHandler(pick_design, pattern=r'^tmpl:')],
            PHOTO_CHOICE: [CallbackQueryHandler(photo_choice, pattern=r'^photo:')],
            PHOTO_WAIT: [MessageHandler(filters.PHOTO, photo_received),
                         CallbackQueryHandler(photo_confirm, pattern=r'^photo:(ok|retry)$')],
            PREVIEW_OK: [CallbackQueryHandler(preview_choice, pattern=r'^pay:')],
            PROOF: [MessageHandler(filters.PHOTO, got_proof)],
            EDIT_CHOICE: [CallbackQueryHandler(edit_choice, pattern=r'^ef:')],
            EDIT_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_value)],
            # ---- new features (merged) ----
            INTV_JOB: [CallbackQueryHandler(_intv_job_cb, pattern=r'^intv:'),
                       MessageHandler(filters.TEXT & ~filters.COMMAND, _intv_job_cb)],
            INTV_TYPE: [CallbackQueryHandler(_intv_type_cb, pattern=r'^intv:')],
            INTV_DIFF: [CallbackQueryHandler(_intv_diff_cb, pattern=r'^intv:')],
            INTV_ASK: [CallbackQueryHandler(_intv_cb2, pattern=r'^intv:'),
                       MessageHandler(filters.TEXT & ~filters.COMMAND, _intv_answer_h)],
            INTV_FEEDBACK: [CallbackQueryHandler(_intv_cb2, pattern=r'^intv:')],
            IMPORT_WAIT: [MessageHandler(filters.ATTACHMENT, feat.import_file)],
            IMPORT_REVIEW: [CallbackQueryHandler(feat.import_review, pattern=r'^imp:')],
            MEM_MENU: [CallbackQueryHandler(feat.memory_cb, pattern=r'^mem:')],
            EXP_PICK: [CallbackQueryHandler(_exp_pick_h, pattern=r'^expf:'),
                       MessageHandler(filters.TEXT & ~filters.COMMAND, feat.exp_custom_text)],
        },
        fallbacks=[CommandHandler('cancel', cancel),
                     CommandHandler('start', start)],
        per_message=False,
    )
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(_mem_consent_dispatch,
                                        pattern=r'^mem:consent:'))
    app.add_handler(CallbackQueryHandler(info_cb, pattern=r'^info:'))
    app.add_handler(CommandHandler('policy', policy_cmd))
    app.add_handler(CommandHandler('faq', faq_cmd))
    # stray-photo fallback: same group, right after conv — fires only when no
    # conversation state consumed the photo (first matching handler per group wins)
    app.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE,
                                   stray_photo_fallback))

    # edit flow (separate conversation, entry from delivered messages)
    edit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_start, pattern=r'^edit:'),
                      CallbackQueryHandler(syserr_start, pattern=r'^syserr:')],
        states={
            EDIT_CHOICE: [CallbackQueryHandler(edit_choice, pattern=r'^ef:')],
            EDIT_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_value)],
            # ---- new features (merged) ----
            INTV_JOB: [CallbackQueryHandler(_intv_job_cb, pattern=r'^intv:'),
                       MessageHandler(filters.TEXT & ~filters.COMMAND, _intv_job_cb)],
            INTV_TYPE: [CallbackQueryHandler(_intv_type_cb, pattern=r'^intv:')],
            INTV_DIFF: [CallbackQueryHandler(_intv_diff_cb, pattern=r'^intv:')],
            INTV_ASK: [CallbackQueryHandler(_intv_cb2, pattern=r'^intv:'),
                       MessageHandler(filters.TEXT & ~filters.COMMAND, _intv_answer_h)],
            INTV_FEEDBACK: [CallbackQueryHandler(_intv_cb2, pattern=r'^intv:')],
            IMPORT_WAIT: [MessageHandler(filters.ATTACHMENT, feat.import_file)],
            IMPORT_REVIEW: [CallbackQueryHandler(feat.import_review, pattern=r'^imp:')],
            MEM_MENU: [CallbackQueryHandler(feat.memory_cb, pattern=r'^mem:')],
            EXP_PICK: [CallbackQueryHandler(_exp_pick_h, pattern=r'^expf:'),
                       MessageHandler(filters.TEXT & ~filters.COMMAND, feat.exp_custom_text)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        per_message=False,
    )
    app.add_handler(edit_conv)

    # AI key entry (separate conversation)
    ai_key_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_ai_key_prompt, pattern=r'^adm:ai_key$')],
        states={
            ADMIN_AI_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND,
                                          admin_ai_key_save)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        per_message=False,
    )
    app.add_handler(ai_key_conv)

    # admin panel
    app.add_handler(CallbackQueryHandler(my_orders, pattern=r'^myorders$'))
    app.add_handler(CommandHandler('admin', admin_entry))
    # Admin Center callbacks
    from telegram.ext import CallbackQueryHandler as _CQH
    app.add_handler(_CQH(ac_handler, pattern=r'^ac:'))
    # Broadcast compose: captures admin's message (group=-1, runs first)
    from telegram.ext import MessageHandler as _MH, filters as _F
    app.add_handler(_MH(bc_compose_handler,
                        _F.ChatType.PRIVATE & _F.User(user_id=ADMIN_ID)),
                    group=-1)
    app.add_handler(_MH(ch_add_handler,
                        _F.TEXT & _F.ChatType.PRIVATE & _F.User(user_id=ADMIN_ID)),
                    group=-1)
    app.add_handler(_MH(welcome_edit_handler,
                        _F.TEXT & _F.ChatType.PRIVATE & _F.User(user_id=ADMIN_ID)),
                    group=-1)
    app.add_handler(_MH(user_search_handler,
                        _F.TEXT & _F.ChatType.PRIVATE & _F.User(user_id=ADMIN_ID)),
                    group=-1)
    app.add_handler(_CQH(rate_handler, pattern=r'^rate:'))
    app.add_handler(_CQH(sub_check_handler, pattern=r'^sub:'))
    app.add_handler(_CQH(ref_handler, pattern=r'^ref:'))
    app.add_handler(CallbackQueryHandler(admin_cb, pattern=r'^adm:(stats|pending|stuck|find|templates|tmpl|audit|back|ai)$'))
    app.add_handler(CallbackQueryHandler(admin_ai_models, pattern=r'^adm:ai_models:'))
    app.add_handler(CallbackQueryHandler(admin_ai_pick, pattern=r'^adm:ai_pick:'))
    # payment decisions (admin)
    app.add_handler(CallbackQueryHandler(admin_pay_decision, pattern=r'^adm_pay:'))
    # user receipt re-upload button (on rejection message / my orders)
    app.add_handler(CallbackQueryHandler(user_reupload_request, pattern=r'^reup:'))
    app.add_handler(CallbackQueryHandler(buy_edits_start, pattern=r'^buyedits:'))
    app.add_handler(CallbackQueryHandler(admin_edit_decision, pattern=r'^adm_edt:'))
    # standalone photo router for re-upload / clearer receipts (runs first,
    # consumes the photo only when explicitly requested, then stops propagation)
    app.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE,
                                   receipt_photo_route), group=-1)
    # admin order search input (one-shot after '🔍 بحث عن طلب')
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
                                   admin_find_input), group=-1)
    log.info('CV bot starting...')
    if not (KEYCARD_NUMBER and str(KEYCARD_NUMBER).strip()):
        log.error('KEYCARD_NUMBER missing - payment instructions disabled until configured')
    import asyncio
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    app.run_polling()


if __name__ == '__main__':
    main()
