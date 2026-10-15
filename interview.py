"""Interview training engine — uses OpenRouter LLM via bot's get_engine()."""
import logging

log = logging.getLogger('cvbot')

DIFFICULTY = {
    'easy': {'ar': 'سهلة', 'en': 'Easy'},
    'medium': {'ar': 'متوسطة', 'en': 'Medium'},
    'hard': {'ar': 'صعبة', 'en': 'Hard'},
}

ITYPE = {
    'general': {'ar': 'عامة', 'en': 'General'},
    'technical': {'ar': 'تخصصية', 'en': 'Technical'},
}

QUESTION_SYSTEM = (
    "You are an expert job interview coach. Generate ONE interview question "
    "in {lang} for a candidate applying as '{job}' (field: {field}). "
    "Interview type: {itype}. Difficulty: {diff}. "
    "Return ONLY the question text, no preamble, no numbering."
)

ANALYZE_SYSTEM = (
    "You are an expert interview coach. The candidate (applying as '{job}') "
    "answered an interview question in {lang}.\n"
    "Question: {question}\n\n"
    "Analyze their answer briefly in {lang} with this exact structure:\n"
    "✅ نقاط القوة: (1-2 lines)\n"
    "🔧 للتحسين: (1-2 lines)\n"
    "💡 صياغة أفضل مقترحة: (1-2 lines)\n"
    "Be honest and specific. Never invent facts about the candidate."
)

HINT_SYSTEM = (
    "You are an interview coach. Give ONE short practical hint in {lang} "
    "for answering this interview question (applying as '{job}'). "
    "Question: {question}\nReturn only the hint, 1-2 lines."
)

SAMPLE_SYSTEM = (
    "You are an interview coach. Write a strong SAMPLE answer in {lang} "
    "to this interview question for someone applying as '{job}'. "
    "Question: {question}\n"
    "Keep it 3-5 lines, realistic, no invented achievements. "
    "Return only the sample answer."
)


async def gen_question(llm, job, field, itype, diff, lang, asked):
    """Generate one interview question via LLM; fallback to templates."""
    lang_name = 'Arabic' if lang == 'ar' else 'English'
    system = QUESTION_SYSTEM.format(
        lang=lang_name, job=job, field=field,
        itype=ITYPE[itype][lang if lang in ('ar', 'en') else 'ar'],
        diff=DIFFICULTY[diff][lang if lang in ('ar', 'en') else 'ar'])
    avoid = ''
    if asked:
        avoid = '\nDo NOT repeat or closely resemble: ' + ' | '.join(asked[-5:])
    try:
        q = await llm(system, f"Generate the question.{avoid}")
        if q and len(q.strip()) > 5:
            return q.strip()
    except Exception as e:
        log.warning('interview question LLM failed: %s', e)
    return _fallback_question(job, itype, diff, lang, len(asked))


async def analyze_answer(llm, job, question, answer, lang):
    lang_name = 'Arabic' if lang == 'ar' else 'English'
    system = ANALYZE_SYSTEM.format(lang=lang_name, job=job, question=question)
    try:
        r = await llm(system, f"Candidate answer:\n{answer}")
        if r and len(r.strip()) > 10:
            return r.strip()
    except Exception as e:
        log.warning('interview analyze LLM failed: %s', e)
    if lang == 'ar':
        return ('✅ نقاط القوة: إجابة واضحة ومباشرة.\n'
                '🔧 للتحسين: أضف مثالًا عمليًا من خبرتك الحقيقية.\n'
                '💡 صياغة أفضل: ابدأ بالنتيجة ثم اشرح الخطوات باختصار.')
    return ('✅ Strengths: clear and direct answer.\n'
            '🔧 To improve: add a real example from your experience.\n'
            '💡 Better phrasing: start with the result, then brief steps.')


async def gen_hint(llm, job, question, lang):
    lang_name = 'Arabic' if lang == 'ar' else 'English'
    system = HINT_SYSTEM.format(lang=lang_name, job=job, question=question)
    try:
        r = await llm(system, 'Give the hint.')
        if r and len(r.strip()) > 5:
            return r.strip()
    except Exception as e:
        log.warning('interview hint LLM failed: %s', e)
    return '💡 ركّز على مثال حقيقي من خبرتك، وكن مختصرًا.' if lang == 'ar' \
        else '💡 Focus on a real example from your experience, keep it brief.'


async def gen_sample(llm, job, question, lang):
    lang_name = 'Arabic' if lang == 'ar' else 'English'
    system = SAMPLE_SYSTEM.format(lang=lang_name, job=job, question=question)
    try:
        r = await llm(system, 'Write the sample answer.')
        if r and len(r.strip()) > 10:
            return r.strip()
    except Exception as e:
        log.warning('interview sample LLM failed: %s', e)
    return '📝 (تعذّر توليد نموذج الآن — حاول لاحقًا)' if lang == 'ar' \
        else '📝 (Could not generate sample now — try later)'


_FALLBACK_Q_AR = {
    'general': [
        'عرّف بنفسك باختصار.',
        'لماذا تريد هذه الوظيفة؟',
        'ما هي نقاط قوتك؟',
        'ما هي نقطة ضعفك وكيف تتعامل معها؟',
        'أين ترى نفسك بعد 5 سنوات؟',
    ],
    'technical': [
        'صف موقفًا صعبًا واجهته بالعمل وكيف حللته.',
        'كيف تتعامل مع ضغط العمل والمواعيد النهائية؟',
        'ما أهم مهارة تمتلكها لهذه الوظيفة؟',
    ],
}
_FALLBACK_Q_EN = {
    'general': [
        'Tell me about yourself briefly.',
        'Why do you want this job?',
        'What are your strengths?',
        'What is your weakness and how do you handle it?',
        'Where do you see yourself in 5 years?',
    ],
    'technical': [
        'Describe a difficult work situation and how you solved it.',
        'How do you handle pressure and deadlines?',
        'What is your most important skill for this role?',
    ],
}


def _fallback_question(job, itype, diff, lang, n):
    bank = _FALLBACK_Q_AR if lang == 'ar' else _FALLBACK_Q_EN
    qs = bank.get(itype, bank['general'])
    return qs[n % len(qs)]
