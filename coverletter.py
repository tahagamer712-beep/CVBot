"""Free cover-letter text generator (AR/EN)."""


def make_cover_letter(d, lang):
    name = d.get('full_name', '')
    title = d.get('job_title', '')
    phone = d.get('phone', '')
    email = d.get('email', '')
    if lang == 'ar':
        return f"""السيد/ة المحترم/ة،

تحية طيبة وبعد،

أتقدم إليكم بطلب التوظيف لشغل وظيفة ({title})، وأرفق لكم سيرتي الذاتية للاطلاع عليها.

{d.get('summary', '')}

أمتلك خبرة عملية في المجال، وأتطلع إلى المساهمة بخبراتي ومهاراتي في تطوير العمل لدى مؤسستكم الموقرة. يسعدني الحضور لمقابلة شخصية في الوقت الذي يناسبكم.

شاكرًا لكم حسن اهتمامكم، وتفضلوا بقبول فائق الاحترام والتقدير.

{name}
الهاتف: {phone}
البريد الإلكتروني: {email}"""
    return f"""Dear Hiring Manager,

I am writing to apply for the position of ({title}). Please find my CV attached for your review.

{d.get('summary', '')}

With my practical experience in the field, I look forward to contributing my skills and expertise to your esteemed organization. I would be glad to attend an interview at your convenience.

Thank you for your time and consideration.

Best regards,
{name}
Phone: {phone}
Email: {email}"""
