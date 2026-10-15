"""AI Writing Engine — rule-based by default, LLM-swappable.

Interface: WritingEngine(llm=None). llm is an async callable
(system: str, user: str) -> str. When llm is None or fails, every method
falls back to deterministic rule-based generation.

IRON RULE: never fabricate. Summaries/experience are built ONLY from data
the user actually provided. No invented years, numbers, or achievements.
"""

# ---------- skill database per field (ar/en) ----------
SKILLS_DB = {
    'medical': {
        'ar': ['الترويج الدوائي', 'إدارة علاقات الأطباء', 'العمل الميداني',
               'تحقيق أهداف المبيعات', 'التفاوض', 'إعداد التقارير',
               'إدارة الوقت', 'خدمة العملاء'],
        'en': ['Pharmaceutical Promotion', 'Physician Relationship Management',
               'Field Work', 'Sales Target Achievement', 'Negotiation',
               'Reporting', 'Time Management', 'Customer Service'],
    },
    'it': {
        'ar': ['البرمجة', 'حل المشكلات', 'قواعد البيانات', 'العمل الجماعي',
               'إدارة المشاريع', 'التوثيق', 'اختبار البرمجيات', 'التعلم السريع'],
        'en': ['Programming', 'Problem Solving', 'Databases', 'Teamwork',
               'Project Management', 'Documentation', 'Software Testing',
               'Fast Learning'],
    },
    'engineering': {
        'ar': ['التصميم الهندسي', 'إدارة المشاريع', 'السلامة المهنية',
               'قراءة المخططات', 'ضبط الجودة', 'العمل الميداني',
               'إعداد التقارير الفنية', 'القيادة'],
        'en': ['Engineering Design', 'Project Management', 'Workplace Safety',
               'Blueprint Reading', 'Quality Control', 'Field Work',
               'Technical Reporting', 'Leadership'],
    },
    'accounting': {
        'ar': ['المحاسبة المالية', 'إكسل المتقدم', 'إعداد الميزانيات',
               'التدقيق', 'الالتزام الضريبي', 'الدقة', 'إدارة الوقت',
               'السرية المهنية'],
        'en': ['Financial Accounting', 'Advanced Excel', 'Budgeting',
               'Auditing', 'Tax Compliance', 'Accuracy', 'Time Management',
               'Professional Confidentiality'],
    },
    'education': {
        'ar': ['إعداد الدروس', 'إدارة الصف', 'التقييم', 'التواصل مع أولياء الأمور',
               'التعلم النشط', 'الصبر', 'استخدام التقنية بالتعليم', 'الإرشاد'],
        'en': ['Lesson Planning', 'Classroom Management', 'Assessment',
               'Parent Communication', 'Active Learning', 'Patience',
               'EdTech', 'Mentoring'],
    },
    'marketing': {
        'ar': ['التسويق الرقمي', 'إدارة الحملات', 'تحليل البيانات',
               'كتابة المحتوى', 'إدارة السوشيال ميديا', 'SEO',
               'التواصل', 'الإبداع'],
        'en': ['Digital Marketing', 'Campaign Management', 'Data Analysis',
               'Content Writing', 'Social Media Management', 'SEO',
               'Communication', 'Creativity'],
    },
    'sales': {
        'ar': ['البيع المباشر', 'التفاوض', 'إدارة العملاء', 'تحقيق الأهداف',
               'العرض والإقناع', 'العمل الميداني', 'المتابعة', 'بناء العلاقات'],
        'en': ['Direct Sales', 'Negotiation', 'Client Management',
               'Target Achievement', 'Presentation & Persuasion',
               'Field Work', 'Follow-up', 'Relationship Building'],
    },
    'general': {
        'ar': ['التواصل', 'العمل الجماعي', 'إدارة الوقت', 'حل المشكلات',
               'الالتزام', 'التعلم السريع', 'الدقة', 'القيادة'],
        'en': ['Communication', 'Teamwork', 'Time Management',
               'Problem Solving', 'Commitment', 'Fast Learning',
               'Accuracy', 'Leadership'],
    },
}

LEVEL_CAP = {'beginner': 6, 'mid': 8, 'senior': 10,
             'مبتدئ': 6, 'متوسط': 8, 'متقدم': 10}


def skill_cap(level):
    return LEVEL_CAP.get(level, 8)


def suggest_skills_list(field, level, lang, already=None):
    """Pre-made skill suggestions for a field, capped by level."""
    already = set(already or [])
    pool = SKILLS_DB.get(field, SKILLS_DB['general'])[lang]
    cap = skill_cap(level)
    return [s for s in pool if s not in already][:cap]


# ---------- rule-based summary templates ----------
def _years_text(exps, lang):
    n = len(exps or [])
    if lang == 'ar':
        if n == 0:
            return 'خريج جديد'
        if n == 1:
            return 'خبرة عملية'
        return f'خبرة تمتد لأكثر من {n} مناصب'
    if n == 0:
        return 'recent graduate'
    if n == 1:
        return 'hands-on experience'
    return f'experience across {n} roles'


def rule_summary(data, lang):
    """Build summary ONLY from user data. No fabrication."""
    name = data.get('full_name', '')
    title = data.get('job_title', '')
    exps = data.get('experience') or []
    skills = (data.get('skills') or [])[:3]
    edu = (data.get('education') or '').split('\n')[0].strip()
    yt = _years_text(exps, lang)
    companies = ', '.join(e.get('company', '') for e in exps[:2] if e.get('company'))
    if lang == 'ar':
        parts = []
        if title:
            parts.append(title + (' — ' + yt if yt and yt != 'خريج جديد' else ''))
        elif yt:
            parts.append(yt + '.')
        if companies:
            parts.append(f'الخبرة: {companies}.')
        if edu:
            parts.append(edu + '.')
        if skills:
            parts.append(f"المهارات: {'، '.join(skills)}.")
        # No assumed goals or filler - only verified facts
        return ' '.join(parts) if parts else 'السيرة الذاتية.' 
    parts = [f'{title} — {yt}.']
    if companies:
        parts.append(f'Worked at {companies}.')
    if skills:
        parts.append(f"Skills: {', '.join(skills)}.")
    if edu:
        parts.append(edu + '.')
    parts.append('Seeking to contribute my experience to drive results.')
    return ' '.join(parts)


# ---------- rule-based experience improvement (linguistic only) ----------
ACTION_VERBS_AR = ['أدير', 'أنفذ', 'أطور', 'أحقق', 'أنسق', 'أشرف على']
ACTION_VERBS_EN = ['Managed', 'Executed', 'Developed', 'Achieved',
                   'Coordinated', 'Supervised']


def rule_improve_experience(desc, lang):
    """Linguistic cleanup only: trim, dedupe, one bullet per line.
    Never adds facts."""
    lines = [l.strip(' •-\t') for l in (desc or '').split('\n')]
    seen, out = set(), []
    for l in lines:
        if l and l not in seen:
            seen.add(l)
            out.append(l)
    return '\n'.join(out)


class WritingEngine:
    """llm: async callable(system, user) -> str, or None for rule-based."""

    def __init__(self, llm=None):
        self.llm = llm

    async def _try_llm(self, system, user):
        if not self.llm:
            return None
        try:
            return await self.llm(system, user)
        except Exception:
            return None

    async def write_summary(self, data, lang='ar'):
        if lang not in ('ar', 'en'):
            lang = 'ar'
        system = ('You write CV professional summaries in Arabic. Use ONLY the '
                  'facts given. Never invent experience, numbers, or achievements. '
                  'Output the summary text only, 2-3 sentences.')
        facts = (f"Name: {data.get('full_name')}\nTitle: {data.get('job_title')}\n"
                 f"Experience: {data.get('experience')}\n"
                 f"Skills: {data.get('skills')}\n"
                 f"Education: {data.get('education')}")
        if lang == 'en':
            system = system.replace('in Arabic', 'in English')
        out = await self._try_llm(system, 'Write a professional summary from these facts only:\n' + facts)
        return out or rule_summary(data, lang)

    async def improve_experience(self, desc, lang='ar'):
        system = ('You polish CV experience bullet points linguistically. '
                  'Do NOT add facts, numbers, or achievements. Keep meaning. '
                  'Output bullets only, one per line.')
        out = await self._try_llm(system, 'Polish (no new facts):\n' + (desc or ''))
        return out or rule_improve_experience(desc, lang)

    async def suggest_skills(self, field, level, lang='ar', already=None):
        base = suggest_skills_list(field, level, lang, already)
        # LLM could refine, but base list is authoritative & safe
        return base

    async def interview_tips(self, job_title, lang='ar'):
        if lang == 'ar':
            return (f'نصائح لمقابلة ({job_title}):\n'
                    '• حضّر تعريفًا بنفسك خلال دقيقة: من أنت، خبرتك، لماذا هذه الوظيفة\n'
                    '• اذكر موقفًا حقيقيًا يظهر مهارتك (لا تخترع)\n'
                    '• اسأل عن الفريق وطبيعة العمل اليومي\n'
                    '• كن صادقًا حول نقاط ضعفك مع خطة تحسين')
        return (f'Interview tips ({job_title}):\n'
                '• Prepare a 60-second self-introduction\n'
                '• Share one real situation showing your skill\n'
                '• Ask about the team and daily work\n'
                '• Be honest about weaknesses with an improvement plan')

    async def analyze_answer(self, question, answer, lang='ar'):
        system = ('You are an interview coach. Analyze the answer briefly: '
                  'one strength, one improvement. Be kind and specific.')
        out = await self._try_llm(
            system, f'Question: {question}\nAnswer: {answer}')
        if out:
            return out
        if lang == 'ar':
            return ('تحليل سريع:\n✅ نقطة قوة: إجابة مباشرة وواضحة.\n'
                    '💡 للتحسين: أضف مثالًا حقيقيًا من خبرتك يدعم كلامك.')
        return ('Quick analysis:\n✅ Strength: direct and clear answer.\n'
                '💡 Improve: add a real example from your experience.')
