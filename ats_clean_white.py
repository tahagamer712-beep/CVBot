"""ATS Clean White — Professional template.

Based on research (2026-10-14):
- Harvard: 10-12pt, no text boxes/colors/shading, margins >= 0.75"
- Indeed: .docx safest, avoid tables/columns, contact in body not header/footer
- LinkedIn: standard section headings, standard fonts, no images/icons
- Single column layout for extraction reliability

Pure white background, black/dark gray text, minimal accent.
"""
import os
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                HRFlowable, KeepTogether)
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics

BLACK = HexColor('#1a1a1a')
DARK_GRAY = HexColor('#333333')
MED_GRAY = HexColor('#666666')
ACCENT = HexColor('#2c5f8a')
LIGHT_LINE = HexColor('#cccccc')

# Arabic reshaping
try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    HAS_ARABIC = True
except ImportError:
    HAS_ARABIC = False


def _ar(text):
    if HAS_ARABIC and any('\u0600' <= c <= '\u06FF' for c in text):
        return get_display(arabic_reshaper.reshape(text))
    return text


def build_ats_clean_white(data, lang, pdf_path):
    """Generate ATS Clean White CV."""
    is_ar = (lang == 'ar')
    align = TA_RIGHT if is_ar else TA_LEFT
    font = 'Amiri' if is_ar else 'Helvetica'
    font_b = 'Amiri-Bold' if is_ar else 'Helvetica-Bold'

    doc = SimpleDocTemplate(
        pdf_path, pagesize=A4,
        leftMargin=19*mm, rightMargin=19*mm,  # ~0.75 inch per Harvard
        topMargin=15*mm, bottomMargin=15*mm,
    )

    # Styles
    s_name = ParagraphStyle('cw_name', fontName=font_b, fontSize=18,
                            leading=22, textColor=BLACK, alignment=TA_CENTER,
                            spaceAfter=2)
    s_title = ParagraphStyle('cw_title', fontName=font, fontSize=12,
                             leading=15, textColor=MED_GRAY,
                             alignment=TA_CENTER, spaceAfter=4)
    s_contact = ParagraphStyle('cw_contact', fontName=font, fontSize=9.5,
                               leading=13, textColor=MED_GRAY,
                               alignment=TA_CENTER, spaceAfter=6)
    s_h = ParagraphStyle('cw_h', fontName=font_b, fontSize=12,
                         leading=15, textColor=BLACK,
                         spaceBefore=12, spaceAfter=4)
    s_body = ParagraphStyle('cw_body', fontName=font, fontSize=10.5,
                            leading=15, textColor=DARK_GRAY,
                            alignment=align, spaceAfter=3)
    s_bullet = ParagraphStyle('cw_bullet', fontName=font, fontSize=10.5,
                              leading=15, textColor=DARK_GRAY,
                              leftIndent=16 if not is_ar else 0,
                              rightIndent=16 if is_ar else 0,
                              bulletIndent=8 if not is_ar else 8,
                              spaceAfter=2, alignment=align)
    s_job = ParagraphStyle('cw_job', fontName=font_b, fontSize=11,
                           leading=14, textColor=BLACK,
                           spaceBefore=6, spaceAfter=1, alignment=align)
    s_meta = ParagraphStyle('cw_meta', fontName=font, fontSize=9.5,
                            leading=13, textColor=MED_GRAY,
                            spaceAfter=2, alignment=align)

    story = []

    def T(text):
        return _ar(text) if is_ar else text

    # Header: name, title, contact (in body, not header per Indeed)
    story.append(Paragraph(T(data.get('full_name', '')), s_name))
    if data.get('job_title'):
        story.append(Paragraph(T(data['job_title']), s_title))
    contact_parts = [p for p in [data.get('phone'), data.get('email'),
                                  data.get('address')] if p]
    if contact_parts:
        story.append(Paragraph(T(' | '.join(contact_parts)), s_contact))
    story.append(HRFlowable(width='100%', thickness=1, color=LIGHT_LINE,
                            spaceAfter=4, spaceBefore=2))

    # Section labels
    labels = {
        'en': {'summary': 'Professional Summary', 'exp': 'Work Experience',
               'edu': 'Education', 'skills': 'Core Skills',
               'training': 'Training & Projects', 'certs': 'Certifications',
               'langs': 'Languages'},
        'ar': {'summary': 'الملخص المهني', 'exp': 'الخبرة العملية',
               'edu': 'التعليم', 'skills': 'المهارات الأساسية',
               'training': 'التدريب والمشاريع', 'certs': 'الشهادات',
               'langs': 'اللغات'},
    }
    L = labels['ar' if is_ar else 'en']

    def section(title):
        story.append(Paragraph(T(title), s_h))
        story.append(HRFlowable(width='100%', thickness=0.5,
                                color=LIGHT_LINE, spaceAfter=4,
                                spaceBefore=1))

    # Summary
    if data.get('summary'):
        section(L['summary'])
        story.append(Paragraph(T(data['summary']), s_body))

    # Experience (reverse chronological)
    exps = data.get('experience', [])
    if exps:
        section(L['exp'])
        for exp in exps:
            story.append(Paragraph(T(exp.get('title', '')), s_job))
            meta = ' | '.join(p for p in [exp.get('company'),
                                           exp.get('period')] if p)
            if meta:
                story.append(Paragraph(T(meta), s_meta))
            desc = exp.get('desc', '')
            if desc:
                for line in desc.split('\n'):
                    line = line.strip().lstrip('•-– ')
                    if line:
                        if lang == 'ar':
                            story.append(Paragraph(
                                T('• ' + line), s_body))
                        else:
                            story.append(Paragraph(
                                T(line), s_bullet, bulletText='•'))

    # Education
    if data.get('education'):
        section(L['edu'])
        edu = data['education']
        if isinstance(edu, list):
            for e in edu:
                story.append(Paragraph(T(str(e)), s_body))
        else:
            story.append(Paragraph(T(str(edu)), s_body))

    # Training & Projects
    if data.get('training'):
        section(L['training'])
        story.append(Paragraph(T(str(data['training'])), s_body))

    # Skills
    skills = data.get('skills', [])
    if skills:
        section(L['skills'])
        if isinstance(skills, list):
            story.append(Paragraph(T(', '.join(skills)), s_body))
        else:
            story.append(Paragraph(T(str(skills)), s_body))

    # Certifications
    if data.get('certifications'):
        section(L['certs'])
        story.append(Paragraph(T(str(data['certifications'])), s_body))

    # Languages
    if data.get('languages'):
        section(L['langs'])
        story.append(Paragraph(T(str(data['languages'])), s_body))

    doc.build(story)
    return pdf_path
