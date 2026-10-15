"""New features: interview training, CV import, professional memory UI, referrals.
Integrated into bot.py via register() — keeps bot.py surgical."""
import logging
import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import db
import interview as intv
import cvimport

log = logging.getLogger('cvbot')

# States: imported lazily from bot.py to avoid circular import.
# Use _S.<NAME> instead of bare names.
class _SLazy:
    """Lazy proxy for bot.py state constants (avoids circular import)."""
    def __getattr__(self, name):
        import bot as _b
        return getattr(_b, name)
S = _SLazy()

FIELDS_20 = [
    ('mgmt', 'الإدارة/HR'), ('sales', 'المبيعات'), ('marketing', 'التسويق'),
    ('cs', 'خدمة العملاء'), ('accounting', 'المحاسبة/المالية'),
    ('pharma', 'الصيدلة/الرعاية الصحية'), ('medrep', 'الدعاية الطبية'),
    ('lab', 'المختبرات'), ('eng', 'الهندسة'), ('it', 'البرمجة/IT'),
    ('design', 'التصميم'), ('edu', 'التعليم/التدريب'), ('law', 'القانون'),
    ('admin', 'إداري/مكتبي'), ('logistics', 'لوجستيات/مخازن'),
    ('industry', 'صناعة/إنتاج'), ('tech', 'فني/صيانة'),
    ('hospitality', 'مطاعم/ضيافة'), ('freelance', 'عمل حر'),
    ('volunteer', 'تطوع'), ('other', 'أخرى'),
]


def _llm_fn(get_engine):
    engine = get_engine()
    async def llm(system, user):
        if engine.llm:
            return await engine.llm(system, user)
        raise RuntimeError('no llm')
    return llm


# ================= INTERVIEW TRAINING =================
async def intv_entry(update, ctx, get_engine):
    q = update.callback_query
    await q.answer()
    ctx.user_data['intv'] = {}
    # suggest job from last order or memory
    sug = ''
    try:
        orders = db.user_orders(q.from_user.id, 1)
        if orders and orders[0].get('job_title'):
            sug = orders[0]['job_title']
    except Exception:
        pass
    if not sug:
        mem = db.memory_get(q.from_user.id)
        if mem and mem['data'].get('target_jobs'):
            sug = mem['data']['target_jobs'][0] if isinstance(
                mem['data']['target_jobs'], list) else mem['data']['target_jobs']
    ctx.user_data['intv_suggest'] = sug
    txt = '🎤 *التدريب للمقابلات*\n\nشنو الوظيفة اللي تريد تتدرب عليها؟'
    kb = []
    if sug:
        kb.append([InlineKeyboardButton(f'💼 {sug}', callback_data='intv:job:sug')])
    kb.append([InlineKeyboardButton('🔙 رجوع', callback_data='intv:cancel')])
    await q.message.reply_text(txt, parse_mode='Markdown',
                               reply_markup=InlineKeyboardMarkup(kb))
    return S.INTV_JOB


async def intv_job(update, ctx, get_engine):
    if update.callback_query:
        q = update.callback_query
        await q.answer()
        if q.data == 'intv:cancel':
            return await _back_to_start(update, ctx)
        job = ctx.user_data.get('intv_suggest', '')
    else:
        job = (update.message.text or '').strip()[:80]
    if not job:
        await update.message.reply_text('اكتب اسم الوظيفة (مثال: مندوب طبي).')
        return S.INTV_JOB
    ctx.user_data['intv']['job'] = job
    kb = [[InlineKeyboardButton('📋 عامة', callback_data='intv:type:general'),
           InlineKeyboardButton('🔬 تخصصية', callback_data='intv:type:technical')],
          [InlineKeyboardButton('🔙 رجوع', callback_data='intv:cancel')]]
    txt = f'💼 الوظيفة: *{job}*\n\nاختر نوع المقابلة:'
    if update.callback_query:
        await update.callback_query.message.reply_text(
            txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update.message.reply_text(
            txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    return S.INTV_TYPE


async def intv_type(update, ctx, get_engine):
    q = update.callback_query
    await q.answer()
    if q.data == 'intv:cancel':
        return await _back_to_start(update, ctx)
    ctx.user_data['intv']['itype'] = q.data.split(':')[2]
    kb = [[InlineKeyboardButton('🟢 سهلة', callback_data='intv:diff:easy'),
           InlineKeyboardButton('🟡 متوسطة', callback_data='intv:diff:medium'),
           InlineKeyboardButton('🔴 صعبة', callback_data='intv:diff:hard')],
          [InlineKeyboardButton('🔙 رجوع', callback_data='intv:cancel')]]
    await q.message.reply_text('اختر مستوى الصعوبة:',
                               reply_markup=InlineKeyboardMarkup(kb))
    return S.INTV_DIFF


async def intv_diff(update, ctx, get_engine):
    q = update.callback_query
    await q.answer()
    if q.data == 'intv:cancel':
        return await _back_to_start(update, ctx)
    ctx.user_data['intv']['diff'] = q.data.split(':')[2]
    ctx.user_data['intv']['asked'] = []
    ctx.user_data['intv']['lang'] = db.get_user_lang(q.from_user.id) if hasattr(
        db, 'get_user_lang') else 'ar'
    return await _ask_next(update, ctx, get_engine, q.message)


async def _ask_next(update, ctx, get_engine, msg):
    d = ctx.user_data['intv']
    lang = d.get('lang', 'ar')
    await msg.reply_text('⏳ أجهّز لك سؤالًا...')
    try:
        llm = _llm_fn(get_engine)
        question = await intv.gen_question(
            llm, d['job'], d.get('field', 'general'),
            d['itype'], d['diff'], lang, d['asked'])
    except Exception as e:
        log.warning('intv llm failed, fallback: %s', e)
        question = intv._fallback_question(
            d['job'], d['itype'], d['diff'], lang, len(d['asked']))
    d['asked'].append(question)
    d['current_q'] = question
    kb = [[InlineKeyboardButton('💡 تلميح', callback_data='intv:hint'),
           InlineKeyboardButton('📝 نموذج إجابة', callback_data='intv:sample')],
          [InlineKeyboardButton('⏭ سؤال جديد', callback_data='intv:next'),
           InlineKeyboardButton('🏁 إنهاء التدريب', callback_data='intv:done')]]
    n = len(d['asked'])
    await msg.reply_text(f'❓ *سؤال {n}:*\n\n{question}\n\n✍️ اكتب إجابتك:',
                         parse_mode='Markdown',
                         reply_markup=InlineKeyboardMarkup(kb))
    return S.INTV_ASK


async def intv_answer(update, ctx, get_engine):
    d = ctx.user_data.get('intv', {})
    if not d.get('current_q'):
        return S.INTV_ASK
    answer = (update.message.text or '').strip()
    if len(answer) < 3:
        await update.message.reply_text('إجابة قصيرة جدًا — حاول تشرح أكثر.')
        return S.INTV_ASK
    lang = d.get('lang', 'ar')
    await update.message.reply_text('⏳ أحلّل إجابتك...')
    try:
        llm = _llm_fn(get_engine)
        analysis = await intv.analyze_answer(
            llm, d['job'], d['current_q'], answer, lang)
    except Exception:
        analysis = await intv.analyze_answer(None, d['job'],
                                             d['current_q'], answer, lang)
    d.setdefault('results', []).append(
        {'q': d['current_q'], 'ok': True})
    kb = [[InlineKeyboardButton('⏭ سؤال جديد', callback_data='intv:next')],
          [InlineKeyboardButton('📊 ملخص أدائي', callback_data='intv:summary'),
           InlineKeyboardButton('🏁 إنهاء', callback_data='intv:done')]]
    await update.message.reply_text(analysis,
                                    reply_markup=InlineKeyboardMarkup(kb))
    return S.INTV_FEEDBACK


async def intv_cb(update, ctx, get_engine):
    q = update.callback_query
    await q.answer()
    d = ctx.user_data.get('intv', {})
    lang = d.get('lang', 'ar')
    action = q.data.split(':')[1]
    if action == 'cancel' or action == 'done':
        n = len(d.get('asked', []))
        txt = (f'🏁 انتهى التدريب — أجبت على {n} أسئلة. بالتوفيق! 🍀'
               if lang == 'ar' else
               f'🏁 Training done — {n} questions answered. Good luck! 🍀')
        await q.message.reply_text(txt)
        ctx.user_data.pop('intv', None)
        return await _back_to_start(update, ctx)
    if action == 'next':
        return await _ask_next(update, ctx, get_engine, q.message)
    if action == 'summary':
        n = len(d.get('asked', []))
        txt = (f'📊 *ملخص أدائك*\n\n• عدد الأسئلة: {n}\n• الوظيفة: {d.get("job","")}\n'
               f'• المستوى: {d.get("diff","")}\n\nاستمر بالتدريب لتطوير إجاباتك! 💪'
               if lang == 'ar' else
               f'📊 *Your summary*\n\n• Questions: {n}\n• Job: {d.get("job","")}')
        await q.message.reply_text(txt, parse_mode='Markdown')
        return S.INTV_FEEDBACK
    # hint / sample need current question
    if not d.get('current_q'):
        await q.message.reply_text('اختر سؤالًا أولًا.')
        return S.INTV_FEEDBACK
    try:
        llm = _llm_fn(get_engine)
        if action == 'hint':
            r = await intv.gen_hint(llm, d['job'], d['current_q'], lang)
        else:
            r = await intv.gen_sample(llm, d['job'], d['current_q'], lang)
    except Exception:
        r = await (intv.gen_hint(None, d['job'], d['current_q'], lang)
                   if action == 'hint'
                   else intv.gen_sample(None, d['job'], d['current_q'], lang))
    await q.message.reply_text(r)
    return S.INTV_FEEDBACK if action in ('hint', 'sample') else INTV_ASK


async def _back_to_start(update, ctx):
    from telegram.ext import ConversationHandler
    ctx.user_data.pop('intv', None)
    # re-show main menu via start handler imported lazily
    import bot as botmod
    fake_update = update
    return await botmod.start(fake_update, ctx)


# ================= CV IMPORT =================
async def import_entry(update, ctx):
    q = update.callback_query
    await q.answer()
    kb = [[InlineKeyboardButton('🔙 رجوع', callback_data='imp:cancel')]]
    await q.message.reply_text(
        '📄 *تطوير سيفي قديم*\n\nأرسل ملف سيرتك القديمة:\n'
        '• PDF أو DOCX\n• أو صورة واضحة للسيرة\n\n'
        'سأستخرج المعلومات وأعرضها عليك للمراجعة قبل المتابعة.',
        parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    return S.IMPORT_WAIT


async def import_file(update, ctx):
    msg = update.message
    data, filename = None, ''
    if msg.document:
        doc = msg.document
        filename = doc.file_name or ''
        if doc.file_size and doc.file_size > 10 * 1024 * 1024:
            await msg.reply_text('⚠️ الملف كبير جدًا (الحد 10MB).')
            return S.IMPORT_WAIT
        f = await doc.get_file()
        data = bytes(await f.download_as_bytearray())
    elif msg.photo:
        photo = msg.photo[-1]
        f = await photo.get_file()
        data = bytes(await f.download_as_bytearray())
        filename = 'photo.jpg'
    else:
        await msg.reply_text('أرسل ملف PDF/DOCX أو صورة.')
        return S.IMPORT_WAIT

    await msg.reply_text('⏳ أستخرج المعلومات...')
    kind = 'photo' if filename == 'photo.jpg' else 'file'
    if kind == 'photo':
        # OCR not available — ask user to type or send clearer
        await msg.reply_text(
            '📷 استلمت الصورة.\n\n'
            '⚠️ استخراج النص من الصور (OCR) غير متوفر حاليًا — '
            'سجّلنا هذا القيد.\n\n'
            'البدائل:\n'
            '• أرسل الملف بصيغة PDF أو DOCX إن توفر\n'
            '• أو اضغط «إنشاء سيفي جديد» وأدخل معلوماتك يدويًا',
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton('📄 إنشاء سيفي جديد',
                                       callback_data='new')]]))
        db.audit(msg.from_user.id, 'import_photo_ocr_missing', '')
        return S.IMPORT_WAIT

    res = cvimport.extract_from_file(data, filename)
    if not res['text']:
        await msg.reply_text(
            '⚠️ تعذّر استخراج النص من الملف. تأكد أنه PDF/DOCX صالح '
            'وليس صورًا ممسوحة، ثم أعد المحاولة.')
        return S.IMPORT_WAIT

    fields = cvimport.parse_fields(res['text'])
    ctx.user_data['imported'] = fields
    review = cvimport.format_review(fields, 'ar')
    kb = [[InlineKeyboardButton('✅ المعلومات صحيحة — أكمل',
                               callback_data='imp:accept')],
          [InlineKeyboardButton('🔙 رجوع', callback_data='imp:cancel')]]
    await msg.reply_text(review, parse_mode='Markdown',
                         reply_markup=InlineKeyboardMarkup(kb))
    # cleanup temp data immediately (policy: no retention of raw files)
    del data
    return S.IMPORT_REVIEW


async def import_review(update, ctx):
    q = update.callback_query
    await q.answer()
    if q.data == 'imp:cancel':
        ctx.user_data.pop('imported', None)
        return await _back_to_start(update, ctx)
    # accept: prefill a new order and jump to job title step
    import bot as botmod
    fields = ctx.user_data.pop('imported', {})
    order_id = botmod.new_order_id()
    db.create_order(order_id, q.from_user.id,
                    q.from_user.username or '')
    pre = {}
    if 'full_name' in fields:
        pre['full_name'] = fields['full_name'][0]
    if 'email' in fields:
        pre['email'] = fields['email'][0]
    if 'phone' in fields:
        pre['phone'] = fields['phone'][0]
    db.set_json(order_id, 'prefill', pre)
    db.set_json(order_id, 'imported_raw',
                fields.get('raw_text', ('', ''))[0][:2000])
    db.update(order_id, status='collecting', payment_status='unpaid')
    ctx.user_data['order_id'] = order_id
    ctx.user_data['prefill'] = pre
    await q.message.reply_text(
        '✅ تم اعتماد المعلومات الأساسية.\n\n'
        'أكمل الآن: ما هي *الوظيفة المستهدفة*؟',
        parse_mode='Markdown')
    return botmod.JOB_TITLE


# ================= PROFESSIONAL MEMORY =================
async def memory_menu(update, ctx):
    q = update.callback_query
    await q.answer()
    mem = db.memory_get(q.from_user.id)
    if not mem or not mem['data']:
        await q.message.reply_text(
            '👔 *ملفي المهني*\n\nلا توجد معلومات محفوظة بعد.\n'
            'ستُعرض عليك الموافقة على الحفظ بعد إكمال أول سيفي.',
            parse_mode='Markdown')
        return S.MEM_MENU
    d = mem['data']
    lines = ['👔 *ملفي المهني*\n']
    labels = {'full_name': 'الاسم', 'phone': 'الهاتف', 'email': 'الإيميل',
              'education': 'التعليم', 'skills': 'المهارات',
              'languages': 'اللغات', 'certs': 'الدورات',
              'target_jobs': 'الوظائف المستهدفة'}
    for k, label in labels.items():
        v = d.get(k)
        if v:
            s = ', '.join(v) if isinstance(v, list) else str(v)
            lines.append(f'• *{label}:* {s[:80]}')
    kb = [[InlineKeyboardButton('🗑 حذف معلوماتي', callback_data='mem:delete')],
          [InlineKeyboardButton('🔙 رجوع', callback_data='mem:back')]]
    await q.message.reply_text('\n'.join(lines), parse_mode='Markdown',
                               reply_markup=InlineKeyboardMarkup(kb))
    return S.MEM_MENU


async def memory_cb(update, ctx):
    q = update.callback_query
    await q.answer()
    if q.data == 'mem:back':
        return await _back_to_start(update, ctx)
    if q.data == 'mem:delete':
        db.memory_delete(q.from_user.id)
        await q.message.reply_text('🗑 تم حذف معلوماتك المهنية المحفوظة.')
        return await _back_to_start(update, ctx)
    return S.MEM_MENU


async def memory_consent_prompt(ctx, user_id, order_data):
    """Ask to save professional memory after first completed CV."""
    if db.memory_get(user_id):
        return  # already has memory
    data = {
        'full_name': order_data.get('full_name', ''),
        'phone': order_data.get('phone', ''),
        'email': order_data.get('email', ''),
        'education': order_data.get('education', ''),
        'skills': order_data.get('skills', ''),
        'languages': order_data.get('languages', ''),
        'certs': order_data.get('certs', ''),
        'target_jobs': [order_data.get('job_title', '')],
        'experience': order_data.get('experience', []),
    }
    # store pending in a simple way via settings-like temp
    import json as _json
    db.set_setting(f'mem_pending_{user_id}', _json.dumps(data, ensure_ascii=False))
    kb = [[InlineKeyboardButton('✅ نعم، احفظها', callback_data='mem:consent:yes'),
           InlineKeyboardButton('❌ لا', callback_data='mem:consent:no')]]
    await ctx.bot.send_message(
        chat_id=user_id,
        text='💾 *تحب أحفظ معلوماتك المهنية؟*\n\n'
             'هذا يسهّل عليك إنشاء سيفي جديد لاحقًا بدون إعادة الإدخال.\n'
             'تكدر تشوفها أو تحذفها بأي وقت من «👔 ملفي المهني».',
        parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))


async def memory_consent_cb(update, ctx):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    if q.data == 'mem:consent:yes':
        raw = db.get_setting(f'mem_pending_{uid}', '')
        if raw:
            import json as _json
            db.memory_save(uid, _json.loads(raw))
            db.set_setting(f'mem_pending_{uid}', '')
        await q.message.reply_text('✅ تم حفظ معلوماتك المهنية.')
    else:
        db.set_setting(f'mem_pending_{uid}', '')
        await q.message.reply_text('تمام — لن أحفظ شيئًا.')
    return await _back_to_start(update, ctx)


# ================= REFERRALS =================
def _ensure_ref_table():
    import sqlite3
    with db._conn() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER NOT NULL,
            referred_id INTEGER NOT NULL UNIQUE,
            created_at TEXT)''')


async def share_menu(update, ctx, bot_username):
    q = update.callback_query
    await q.answer()
    _ensure_ref_table()
    uid = q.from_user.id
    link = f'https://t.me/{bot_username}?start=ref_{uid}'
    import sqlite3
    with db._conn() as c:
        n = c.execute('SELECT COUNT(*) c FROM referrals WHERE referrer_id=?',
                      (uid,)).fetchone()['c']
    msg = ('📤 *مشاركة البوت*\n\n'
           'شارك رابطك الخاص مع أصدقائك:\n'
           f'`{link}`\n\n'
           f'👥 عدد المنضمين عبر رابطك: *{n}*\n\n'
           'انسخ الرابط وأرسله لأصدقائك 👇')
    # NOTE: no auto rewards — tracking only, per Taha's rule
    await q.message.reply_text(msg, parse_mode='Markdown')
    return None


def track_referral(new_user_id, referrer_id):
    """Record referral. Returns False if self-referral or duplicate."""
    if not referrer_id or int(referrer_id) == int(new_user_id):
        return False
    _ensure_ref_table()
    import sqlite3
    try:
        with db._conn() as c:
            c.execute(
                'INSERT INTO referrals (referrer_id, referred_id, created_at)'
                ' VALUES (?,?,?)',
                (int(referrer_id), int(new_user_id), db._now()))
        db.audit(int(referrer_id), 'referral',
                 f'referred={new_user_id}')
        return True
    except sqlite3.IntegrityError:
        return False  # already referred


# ================= EXPERIENCE FIELD PICKER =================
def exp_picker_kb(selected):
    rows = []
    row = []
    for fid, label in FIELDS_20:
        mark = '✅ ' if fid in selected else ''
        row.append(InlineKeyboardButton(f'{mark}{label}',
                                       callback_data=f'expf:{fid}'))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton('✍️ خبرة مخصصة', callback_data='expf:custom')])
    rows.append([InlineKeyboardButton('🚫 لا أمتلك خبرة عملية',
                                     callback_data='expf:none')])
    rows.append([InlineKeyboardButton(f'✅ تأكيد ({len(selected)})',
                                     callback_data='expf:done')])
    return InlineKeyboardMarkup(rows)


async def exp_pick_entry(update, ctx):
    """Optional entry: replace EXP_TITLE text step with button picker."""
    q = update.callback_query
    await q.answer()
    ctx.user_data['exp_fields'] = []
    await q.message.reply_text(
        '💼 *اختر مجالات خبرتك* (يمكنك اختيار أكثر من واحد):',
        parse_mode='Markdown', reply_markup=exp_picker_kb([]))
    return S.EXP_PICK


async def exp_pick_cb(update, ctx, get_engine):
    q = update.callback_query
    await q.answer()
    sel = ctx.user_data.setdefault('exp_fields', [])
    fid = q.data.split(':')[1]
    if fid == 'done':
        import bot as botmod
        if not sel:
            await q.message.reply_text('اختر مجالًا واحدًا على الأقل أو «لا أمتلك خبرة».')
            return S.EXP_PICK
        # AI suggests tasks for review only
        labels = [l for f, l in FIELDS_20 if f in sel]
        ctx.user_data['exp_fields_labels'] = labels
        await q.message.reply_text(
            '📝 مجالاتك: ' + '، '.join(labels) +
            '\n\nالآن اكتب *المسمى الوظيفي* لأول خبرة:',
            parse_mode='Markdown')
        return botmod.EXP_TITLE
    if fid == 'none':
        import bot as botmod
        ctx.user_data['exp_fields_labels'] = []
        ctx.user_data['no_experience'] = True
        await q.message.reply_text('تمام — سنتجاوز قسم الخبرة.\n\nما هو *مستواك التعليمي*؟',
                                   parse_mode='Markdown')
        return botmod.EDUCATION
    if fid == 'custom':
        await q.message.reply_text('✍️ اكتب مجال خبرتك المخصصة:')
        ctx.user_data['exp_custom_pending'] = True
        return S.EXP_PICK
    if fid in sel:
        sel.remove(fid)
    else:
        sel.append(fid)
    await q.message.edit_reply_markup(reply_markup=exp_picker_kb(sel))
    return S.EXP_PICK


async def exp_custom_text(update, ctx):
    if ctx.user_data.pop('exp_custom_pending', False):
        custom = (update.message.text or '').strip()[:60]
        if custom:
            sel = ctx.user_data.setdefault('exp_fields', [])
            sel.append(f'custom:{custom}')
            await update.message.reply_text(
                f'✅ أُضيفت: {custom}\n\nاختر مجالات أخرى أو اضغط تأكيد:',
                reply_markup=exp_picker_kb(sel))
            return S.EXP_PICK
    return S.EXP_PICK
