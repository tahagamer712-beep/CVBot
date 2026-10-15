"""Template library — 12 named templates. Only ready=1 templates are shown.

Architecture: each template maps to a design_key implemented in cvgen.py.
Adding a new template = register metadata here + implement design_key once.
Unready templates are never displayed to users.
"""
import db

TEMPLATES = [
    dict(id='ats_minimal', name_ar='ATS Minimal',
         name_en='ATS Minimal',
         description_ar='بسيط بعمود واحد — متوافق تمامًا مع أنظمة التوظيف الآلية',
         best_for_ar='التقديم عبر مواقع التوظيف والشركات الكبيرة',
         languages='ar,en', ats_compatible=1, ready=1, sort_order=1,
         design_key='formal'),
    dict(id='modern_corporate', name_ar='Modern Corporate',
         name_en='Modern Corporate',
         description_ar='عصري بترويسة داكنة أنيقة — للشركات الحديثة',
         best_for_ar='التقنية والتسويق والشركات الخاصة',
         languages='ar,en', ats_compatible=0, ready=1, sort_order=3,
         design_key='modern'),
    dict(id='modern_executive', name_ar='Modern Executive',
         name_en='Modern Executive',
         description_ar='سايدبار كحلي فاخر — للخبرات والقيادات',
         best_for_ar='أصحاب الخبرة والمدراء والاختصاصات',
         languages='ar,en', ats_compatible=0, ready=1, sort_order=13,
         design_key='modern_executive'),
    dict(id='modern_professional', name_ar='Modern Professional',
         name_en='Modern Professional',
         description_ar='بانر علوي أنيق بأعمدة مهارات — للخريجين والمهنيين',
         best_for_ar='الخريجون وأصحاب الخبرات بمختلف المستويات',
         languages='ar,en', ats_compatible=0, ready=1, sort_order=14,
         design_key='modern_professional'),
    dict(id='ats_professional', name_ar='ATS Professional',
         name_en='ATS Professional',
         description_ar='عمود واحد خطي متوافق مع أنظمة التوظيف',
         best_for_ar='التقديم عبر مواقع التوظيف وأنظمة ATS',
         languages='ar,en', ats_compatible=1, ready=1, sort_order=15,
         design_key='ats_professional'),
    dict(id='classic_professional', name_ar='Classic Professional',
         name_en='Classic Professional',
         description_ar='كلاسيكي راقٍ بخط واضح وتقسيم تقليدي',
         best_for_ar='الوظائف الإدارية والمكتبية',
         languages='ar,en', ats_compatible=1, ready=0, sort_order=4,
         design_key='formal'),
    dict(id='graduate', name_ar='خريج جديد',
         name_en='Graduate / Entry-Level',
         description_ar='يبرز التعليم والمشاريع والتدريب لحديثي التخرج',
         best_for_ar='الخريجون الجدد وبدون خبرة',
         languages='ar,en', ats_compatible=1, ready=0, sort_order=5,
         design_key='formal'),
    dict(id='experienced', name_ar='خبرة عملية',
         name_en='Experienced Professional',
         description_ar='يبرز الإنجازات والخبرات المتراكمة',
         best_for_ar='أصحاب الخبرة 3+ سنوات',
         languages='ar,en', ats_compatible=0, ready=0, sort_order=6,
         design_key='modern'),
    dict(id='executive', name_ar='الإدارة العليا',
         name_en='Executive',
         description_ar='فاخر وموجز — للقيادات والمدراء',
         best_for_ar='المدراء والتنفيذيون',
         languages='en', ats_compatible=0, ready=0, sort_order=7,
         design_key='formal'),
    dict(id='academic', name_ar='أكاديمي',
         name_en='Academic / Research',
         description_ar='للأبحاث والمنشورات والمؤهلات العلمية',
         best_for_ar='الجامعات والمراكز البحثية',
         languages='ar,en', ats_compatible=1, ready=0, sort_order=8,
         design_key='formal'),
    dict(id='medical', name_ar='طبي',
         name_en='Medical / Healthcare',
         description_ar='لمسة طبية مميزة بألوان هادئة',
         best_for_ar='الأطباء والصيادلة والقطاع الصحي',
         languages='ar,en', ats_compatible=0, ready=0, sort_order=9,
         design_key='medical'),
    dict(id='technical', name_ar='تقني/هندسي',
         name_en='Technical / Engineering',
         description_ar='يبرز المهارات التقنية والمشاريع',
         best_for_ar='المهندسون والمبرمجون والفنيون',
         languages='ar,en', ats_compatible=1, ready=0, sort_order=10,
         design_key='modern'),
    dict(id='sales_marketing', name_ar='مبيعات وتسويق',
         name_en='Sales / Marketing',
         description_ar='نابض بالحياة — يبرز الأرقام والإنجازات',
         best_for_ar='المبيعات والتسويق وخدمة العملاء',
         languages='ar,en', ats_compatible=0, ready=0, sort_order=11,
         design_key='modern'),
    dict(id='creative', name_ar='إبداعي',
         name_en='Creative Portfolio',
         description_ar='جريء ومميز — للمصممين والمبدعين',
         best_for_ar='التصميم والإعلام والمحتوى',
         languages='en', ats_compatible=0, ready=0, sort_order=12,
         design_key='modern'),
]


def seed_templates():
    for t in TEMPLATES:
        db.upsert_template(t)


def design_for_template(template_id):
    """Return the design_key for a template id (fallback: formal)."""
    for t in TEMPLATES:
        if t['id'] == template_id:
            return t['design_key']
    return 'formal'

# ATS Clean White — added 2026-10-14 (research-backed)
TEMPLATES.append({
    'id': 'ats_clean_white',
    'name_ar': 'ATS أبيض نظيف',
    'name_en': 'ATS Clean White',
    'description_ar': 'أبيض بالكامل بعمود واحد — مبني على أبحاث Harvard/Indeed/LinkedIn',
    'best_for_ar': 'أقصى توافق مع أنظمة ATS والطباعة',
    'languages': 'ar,en',
    'ats_compatible': 1,
    'ready': 1,
    'sort_order': 99,
    'design_key': 'formal',
})
