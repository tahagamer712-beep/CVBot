"""ATS Professional template — single-column, linear, parser-optimized.

Based on research (Jobscan 2025, Harvard OCS, Greenhouse/Workday docs):
- Single column, top-to-bottom reading order
- Standard fonts (Helvetica/Arial equivalent)
- Standard section headings
- Contact info in body (not header/footer)
- No tables, graphics, text boxes, or sidebars
- Standard bullets
"""
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, inch
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                HRFlowable, KeepTogether)
from reportlab.lib.colors import HexColor
import cvgen


def _v(text, lang):
    return cvgen.visual(text, lang)


def generate_ats_pro(data, lang, outpath, photo_path=None):
    """Generate ATS-optimized single-column resume."""
    # Note: photo intentionally IGNORED for ATS (parsers can't read images)
    W, H = A4
    # 0.7 inch margins per research
    M = 0.7 * inch

    # Colors: minimal, high contrast
    DARK = HexColor('#1a1a1a')
    GRAY = HexColor('#444444')
    ACCENT = HexColor('#2c3e50')

    # Typography: Helvetica for EN, Amiri for AR (supports Arabic glyphs)
    _fn = 'Helvetica'
    _fnb = 'Helvetica-Bold'
    if lang == 'ar':
        _fn = 'Amiri'
        _fnb = 'Amiri-Bold'
    s_name = ParagraphStyle('ats_name', fontName=_fnb,
                            fontSize=16, leading=19, textColor=DARK,
                            alignment=TA_CENTER)
    s_title = ParagraphStyle('ats_title', fontName=_fn,
                             fontSize=11, leading=14, textColor=GRAY,
                             alignment=TA_CENTER)
    s_contact = ParagraphStyle('ats_contact', fontName=_fn,
                               fontSize=9, leading=12, textColor=GRAY,
                               alignment=TA_CENTER)
    s_h = ParagraphStyle('ats_h', fontName=_fnb,
                         fontSize=12, leading=15, textColor=ACCENT,
                         spaceBefore=10, spaceAfter=4)
    s_body = ParagraphStyle('ats_body', fontName=_fn,
                            fontSize=10.5, leading=14, textColor=DARK,
                            alignment=TA_LEFT, spaceAfter=3)
    s_bullet = ParagraphStyle('ats_bullet', fontName=_fn,
                              fontSize=10.5, leading=14, textColor=DARK,
                              leftIndent=14, firstLineIndent=0,
                              bulletIndent=6, spaceAfter=2,
                              alignment=TA_LEFT)
    s_job = ParagraphStyle('ats_job', fontName=_fnb,
                           fontSize=11, leading=14, textColor=DARK,
                           spaceBefore=6, spaceAfter=1)
    s_meta = ParagraphStyle('ats_meta', fontName=_fn,
                            fontSize=9.5, leading=12, textColor=GRAY,
                            spaceAfter=3)

    # RTL/LTR alignment
    if lang == 'ar':
        for s in (s_body, s_bullet, s_job):
            s.alignment = TA_RIGHT
        s_bullet.leftIndent = 0
        s_bullet.rightIndent = 14
        s_bullet.bulletIndent = 6

    doc = SimpleDocTemplate(outpath, pagesize=A4,
                            leftMargin=M, rightMargin=M,
                            topMargin=M, bottomMargin=M,
                            title=f"CV - {data.get('full_name', '')}")
    story = []
    L = cvgen.L[lang] if lang in cvgen.L else cvgen.L['en']

    # NAME (centered, 16pt bold)
    story.append(Paragraph(_v(data.get('full_name', ''), lang), s_name))
    # Job title
    if data.get('job_title'):
        story.append(Paragraph(_v(data['job_title'], lang), s_title))
    story.append(Spacer(1, 4))

    # CONTACT INFO (in body, pipe-separated, no icons)
    contacts = []
    if data.get('phone'):
        contacts.append(_v(data['phone'], lang))
    if data.get('email'):
        contacts.append(_v(data['email'], lang))
    if data.get('address'):
        contacts.append(_v(data['address'], lang))
    if contacts:
        sep = ' | '
        story.append(Paragraph(sep.join(contacts), s_contact))
    story.append(Spacer(1, 6))
    story.append(HRFlowable(width='100%', thickness=1, color=ACCENT))
    story.append(Spacer(1, 4))

    def section(title_key, title_en):
        title = L.get(title_key, title_en)
        story.append(Paragraph(_v(title, lang), s_h))
        story.append(HRFlowable(width='100%', thickness=0.5, color=HexColor('#cccccc')))
        story.append(Spacer(1, 4))

    # PROFESSIONAL SUMMARY
    if data.get('summary'):
        section('summary', 'Professional Summary')
        story.append(Paragraph(_v(data['summary'], lang), s_body))
        story.append(Spacer(1, 4))

    # WORK EXPERIENCE (reverse chronological)
    exps = data.get('experience') or []
    if exps:
        section('experience', 'Work Experience')
        for exp in exps:
            block = []
            # Job title (bold)
            if exp.get('title'):
                block.append(Paragraph(_v(exp['title'], lang), s_job))
            # Company | Period (single line for parser clarity)
            meta_parts = []
            if exp.get('company'):
                meta_parts.append(_v(exp['company'], lang))
            if exp.get('period'):
                meta_parts.append(_v(exp['period'], lang))
            if meta_parts:
                block.append(Paragraph(' | '.join(meta_parts), s_meta))
            # Bullets (standard •)
            # For RTL: embed bullet in text (ReportLab bullet
            # positioning is LTR-oriented and disconnects visually)
            desc = exp.get('desc', '')
            for line in desc.split('\n'):
                line = line.strip().lstrip('-• ')
                if line:
                    if lang == 'ar':
                        block.append(Paragraph(
                            _v('• ' + line, lang), s_body))
                    else:
                        block.append(Paragraph(
                            _v(line, lang), s_bullet, bulletText='•'))
            # Keep job block together (don't split header from bullets)
            if len(block) > 3:
                story.append(KeepTogether(block[:2]))
                story.extend(block[2:])
            else:
                story.extend(block)
        story.append(Spacer(1, 4))

    # EDUCATION
    if data.get('education'):
        section('education', 'Education')
        for line in str(data['education']).split('\n'):
            if line.strip():
                story.append(Paragraph(_v(line.strip(), lang), s_body))
        story.append(Spacer(1, 4))

    # SKILLS (comma-separated for parser, not grid)
    skills = data.get('skills') or []
    if isinstance(skills, str):
        skills = [s.strip() for s in skills.split('\n') if s.strip()]
    if skills:
        section('skills', 'Skills')
        # Comma-separated is most parser-friendly
        story.append(Paragraph(_v(', '.join(skills), lang), s_body))
        story.append(Spacer(1, 4))

    # LANGUAGES
    langs = data.get('languages') or []
    if isinstance(langs, str):
        langs = [s.strip() for s in langs.split('\n') if s.strip()]
    if langs:
        section('languages', 'Languages')
        story.append(Paragraph(_v(', '.join(langs), lang), s_body))
        story.append(Spacer(1, 4))

    # CERTIFICATIONS
    if data.get('certs'):
        section('certs', 'Certifications')
        for line in str(data['certs']).split('\n'):
            if line.strip():
                story.append(Paragraph(_v(line.strip(), lang), s_bullet,
                                       bulletText='•'))
    # ACHIEVEMENTS
    achs = data.get('achievements') or []
    if isinstance(achs, str):
        achs = [a.strip() for a in achs.split('\n') if a.strip()]
    if achs:
        section('achievements', 'Achievements')
        for a in achs:
            story.append(Paragraph(_v(a, lang), s_bullet, bulletText='•'))

    doc.build(story)
    return outpath
