"""CV generation: PDF (ReportLab) + DOCX (python-docx), 3 designs, AR/EN with RTL."""
import os
import arabic_reshaper
from reportlab.lib.pagesizes import A4
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                HRFlowable, Table, TableStyle)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER

BASE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(BASE, 'fonts')
pdfmetrics.registerFont(TTFont('Amiri', os.path.join(FONT_DIR, 'Amiri-Regular.ttf')))
pdfmetrics.registerFont(TTFont('Amiri-Bold', os.path.join(FONT_DIR, 'Amiri-Bold.ttf')))

# ---------- BiDi (minimal, no python-bidi dependency) ----------
def _is_rtl(ch):
    cp = ord(ch)
    return (0x0590 <= cp <= 0x08FF) or (0xFB1D <= cp <= 0xFDFF) or (0xFE70 <= cp <= 0xFEFF)

def has_rtl(text):
    """True if text contains any RTL character."""
    return any(_is_rtl(c) for c in str(text or ''))

def visual(text, base_rtl=False):
    """Logical-order mixed text -> visual order for ReportLab (LTR renderer).
    Uses python-bidi (full Unicode BiDi algorithm) + arabic_reshaper.
    base_rtl=True: paragraph base direction is RTL (Arabic CV).
    base_rtl=False: paragraph base direction is LTR (English CV with Arabic snippets)."""
    if not text:
        return ''
    text = str(text)
    if not has_rtl(text):
        return text
    try:
        from bidi.algorithm import get_display
        reshaped = arabic_reshaper.reshape(text)
        return get_display(reshaped, base_dir='R' if base_rtl else 'L')
    except Exception:
        runs, cur, cur_rtl = [], '', None
        for ch in text:
            rtl = _is_rtl(ch)
            if cur_rtl is None:
                cur_rtl = rtl
            if rtl == cur_rtl:
                cur += ch
            else:
                runs.append((cur, cur_rtl))
                cur, cur_rtl = ch, rtl
        if cur:
            runs.append((cur, cur_rtl))
        shaped = []
        for run, rtl in runs:
            if rtl:
                shaped.append(arabic_reshaper.reshape(run)[::-1])
            else:
                shaped.append(run)
        if base_rtl:
            shaped = shaped[::-1]
        return ''.join(shaped)

# ---------- Labels ----------
L = {
    'ar': {
        'summary': 'الملخص المهني',
        'experience': 'الخبرات العملية',
        'education': 'التعليم',
        'certs': 'الشهادات والدورات',
        'skills': 'المهارات',
        'languages': 'اللغات',
        'present': 'حتى الآن',
    },
    'en': {
        'summary': 'Professional Summary',
        'experience': 'Professional Experience',
        'education': 'Education',
        'certs': 'Certifications',
        'skills': 'Skills',
        'languages': 'Languages',
        'present': 'Present',
    },
}

PAGE_W, PAGE_H = A4
MARGIN = 42

def _styles(lang):
    rtl = lang == 'ar'
    base_align = TA_RIGHT if rtl else TA_LEFT
    return {
        'name': ParagraphStyle('name', fontName='Amiri-Bold', fontSize=20,
                               leading=24, alignment=TA_CENTER, spaceAfter=2),
        'title': ParagraphStyle('title', fontName='Amiri', fontSize=11.5,
                                leading=15, alignment=TA_CENTER,
                                textColor=HexColor('#444444'), spaceAfter=4),
        'contact': ParagraphStyle('contact', fontName='Amiri', fontSize=9,
                                  leading=12, alignment=TA_CENTER,
                                  textColor=HexColor('#555555'), spaceAfter=6),
        'h2': ParagraphStyle('h2', fontName='Amiri-Bold', fontSize=12.5,
                             leading=16, alignment=base_align,
                             spaceBefore=10, spaceAfter=4),
        'body': ParagraphStyle('body', fontName='Amiri', fontSize=10,
                               leading=14.5, alignment=base_align, spaceAfter=3),
        'bullet': ParagraphStyle('bullet', fontName='Amiri', fontSize=10,
                                 leading=14.5, alignment=base_align,
                                 leftIndent=14 if not rtl else 0,
                                 rightIndent=14 if rtl else 0,
                                 spaceAfter=2, bulletIndent=6 if not rtl else 0),
        'jobhead': ParagraphStyle('jobhead', fontName='Amiri-Bold', fontSize=10.5,
                                  leading=14, alignment=base_align, spaceBefore=6,
                                  spaceAfter=1),
        'period': ParagraphStyle('period', fontName='Amiri', fontSize=9.5,
                                 leading=13, alignment=TA_RIGHT if rtl else TA_LEFT,
                                 textColor=HexColor('#666666')),
        'center': ParagraphStyle('center', fontName='Amiri', fontSize=10,
                                 leading=14, alignment=TA_CENTER),
    }

def _v(text, lang):
    # BUGFIX: Arabic text inside English CVs must be shaped too,
    # but with LTR base direction (base_rtl=False).
    if lang == 'ar':
        return visual(text, base_rtl=True)
    if has_rtl(text):
        return visual(text, base_rtl=False)
    return str(text or '')

def _contact_line(d, lang):
    parts = [d.get('phone', ''), d.get('email', ''), d.get('address', '')]
    parts = [p for p in parts if p]
    sep = '  |  '
    joined = sep.join(parts)
    if lang == 'ar':
        return visual(joined, base_rtl=True)
    if has_rtl(joined):
        return visual(joined, base_rtl=False)
    return joined

def _section(story, styles, lang, key):
    styles_h2 = styles['h2']
    story.append(Paragraph(_v(L[lang][key], lang), styles_h2))
    story.append(HRFlowable(width='100%', thickness=1.2,
                            color=HexColor('#222222'), spaceAfter=6, spaceBefore=2))

def _experience_block(story, styles, lang, exp):
    rtl = lang == 'ar'
    head = f"{exp.get('title','')} — {exp.get('company','')}"
    prow = [
        Paragraph(_v(head, lang), styles['jobhead']),
        Paragraph(_v(exp.get('period', ''), lang), styles['period']),
    ]
    if rtl:
        prow = prow[::-1]
    t = Table([prow], colWidths=[380, 113])
    t.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    story.append(t)
    desc = exp.get('desc', '')
    if desc:
        for line in [l.strip() for l in desc.split('\n') if l.strip()]:
            story.append(Paragraph(_v(f'• {line}', lang), styles['bullet'],
                                   bulletText=''))

def _body_sections(story, styles, lang, d):
    if d.get('summary'):
        _section(story, styles, lang, 'summary')
        story.append(Paragraph(_v(d['summary'], lang), styles['body']))
    exps = d.get('experience') or []
    if exps:
        _section(story, styles, lang, 'experience')
        for e in exps:
            _experience_block(story, styles, lang, e)
    if d.get('education'):
        _section(story, styles, lang, 'education')
        for line in [l.strip() for l in d['education'].split('\n') if l.strip()]:
            story.append(Paragraph(_v(line, lang), styles['body']))
    certs = d.get('certs') or []
    if certs:
        _section(story, styles, lang, 'certs')
        for c in certs:
            story.append(Paragraph(_v(f'• {c}', lang), styles['bullet']))
    skills = d.get('skills') or []
    if skills:
        _section(story, styles, lang, 'skills')
        story.append(Paragraph(_v(' • '.join(skills), lang), styles['body']))
    langs = d.get('languages') or []
    if langs:
        _section(story, styles, lang, 'languages')
        story.append(Paragraph(_v(' • '.join(langs), lang), styles['body']))

# ================= DESIGN 1: formal =================
def _design_formal(story, styles, lang, d):
    story.append(Paragraph(_v(d.get('full_name', ''), lang), styles['name']))
    if d.get('job_title'):
        story.append(Paragraph(_v(d['job_title'], lang), styles['title']))
    story.append(Paragraph(_contact_line(d, lang), styles['contact']))
    story.append(HRFlowable(width='100%', thickness=1.5, color=HexColor('#222222'),
                            spaceAfter=4, spaceBefore=2))
    _body_sections(story, styles, lang, d)

# ================= DESIGN 2: modern (dark header) =================
DARK = HexColor('#16161f')

def _modern_header(canvas, doc, lang, d):
    canvas.saveState()
    canvas.setFillColor(DARK)
    canvas.rect(0, PAGE_H - 150, PAGE_W, 150, stroke=0, fill=1)
    canvas.setFillColor(HexColor('#ffffff'))
    canvas.setFont('Amiri-Bold', 21)
    name = _v(d.get('full_name', ''), lang)
    if lang == 'ar':
        canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 62, name)
    else:
        canvas.drawString(MARGIN, PAGE_H - 62, name)
    canvas.setFont('Amiri', 11)
    canvas.setFillColor(HexColor('#cfcfd8'))
    title = _v(d.get('job_title', ''), lang)
    if lang == 'ar':
        canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 88, title)
    else:
        canvas.drawString(MARGIN, PAGE_H - 88, title)
    canvas.setFillColor(HexColor('#ffffff'))
    canvas.setFont('Amiri', 8.5)
    parts = [p for p in [d.get('phone', ''), d.get('email', ''), d.get('address', '')] if p]
    contact_v = _v('   |   '.join(parts), lang)
    cy = PAGE_H - 118
    if lang == 'ar':
        canvas.drawRightString(PAGE_W - MARGIN, cy, contact_v)
    else:
        canvas.drawString(MARGIN, cy, contact_v)
    canvas.restoreState()

def _design_modern(story, styles, lang, d):
    story.append(Spacer(1, 118))
    styles['h2'].textColor = DARK
    _body_sections(story, styles, lang, d)

# ================= DESIGN 3: medical (teal accent) =================
TEAL = HexColor('#0e7c7b')
TEAL_DARK = HexColor('#0a5e5d')

def _design_medical(story, styles, lang, d):
    rtl = lang == 'ar'
    name_style = ParagraphStyle('mname', parent=styles['name'],
                                alignment=TA_RIGHT if rtl else TA_LEFT,
                                textColor=TEAL_DARK, fontSize=22)
    story.append(Paragraph(_v(d.get('full_name', ''), lang), name_style))
    if d.get('job_title'):
        ts = ParagraphStyle('mtitle', parent=styles['title'],
                            alignment=TA_RIGHT if rtl else TA_LEFT,
                            textColor=HexColor('#333333'))
        story.append(Paragraph(_v(d['job_title'], lang), ts))
    story.append(Paragraph(_contact_line(d, lang),
                           ParagraphStyle('mcontact', parent=styles['contact'],
                                          alignment=TA_RIGHT if rtl else TA_LEFT)))
    story.append(HRFlowable(width='100%', thickness=2.5, color=TEAL,
                            spaceAfter=6, spaceBefore=4))
    styles['h2'].textColor = TEAL_DARK
    _body_sections(story, styles, lang, d)

# ================= public API =================
def mask_contact(d):
    """Return a copy with sensitive contact info partially masked (for preview)."""
    d = dict(d)
    phone = str(d.get('phone') or '')
    if len(phone) > 4:
        d['phone'] = phone[:4] + ' *** *** ' + phone[-3:]
    email = str(d.get('email') or '')
    if '@' in email:
        user, dom = email.split('@', 1)
        d['email'] = (user[:1] + '***@' + dom) if user else email
    return d


def _draw_watermark(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(HexColor('#cc0000'))
    canvas.setFont('Amiri-Bold', 42)
    canvas.rotate(35)
    # repeated diagonal watermark
    for y in range(-200, 1100, 220):
        canvas.setFillAlpha(0.10)
        canvas.drawString(60, y, 'PREVIEW - NOT FINAL')
    canvas.restoreState()


def generate_pdf(data, lang, design, outpath, watermark=False,
                 photo_path=None):
    """data: dict; lang: 'ar'|'en'; design: formal|modern|medical|modern_executive|modern_professional."""
    styles = _styles(lang)
    story = []
    if photo_path and os.path.exists(photo_path):
        from reportlab.platypus import Image as RLImage
        try:
            from reportlab.lib.utils import ImageReader
            ImageReader(photo_path).getSize()  # force decode now; raises for bad files
            img = RLImage(photo_path, width=72, height=86)
            img.hAlign = 'RIGHT' if lang == 'ar' else 'LEFT'
            story.append(img)
            story.append(Spacer(1, 4))
        except Exception:
            pass
    on_page = None
    if design == 'formal':
        _design_formal(story, styles, lang, data)
    elif design == 'modern':
        _design_modern(story, styles, lang, data)
        def _modern_pg(canvas, doc):
            _modern_header(canvas, doc, lang, data)
            if watermark:
                _draw_watermark(canvas, doc)
        on_page = _modern_pg
    elif design == 'medical':
        _design_medical(story, styles, lang, data)
    elif design == 'ats_professional':
        import ats_template
        return ats_template.generate_ats_pro(
            data, lang, outpath, photo_path=photo_path)
    elif design == 'ats_clean_white':
        import ats_clean_white
        return ats_clean_white.build_ats_clean_white(data, lang, outpath)
    elif design == 'ats_minimal':
        # ats_minimal had no generator; maps to clean white (minimal ATS design)
        import ats_clean_white
        return ats_clean_white.build_ats_clean_white(data, lang, outpath)
    elif design == 'modern_executive':
        import modern_templates
        return modern_templates.generate_executive(
            data, lang, outpath, photo_path, watermark=watermark)
    elif design == 'modern_professional':
        import modern_templates
        return modern_templates.generate_professional(
            data, lang, outpath, photo_path, watermark=watermark)
    else:
        raise ValueError(f'unknown design {design}')

    def _wm_only(canvas, doc):
        if watermark:
            _draw_watermark(canvas, doc)

    top_margin = 170 if design == 'modern' else MARGIN
    doc = SimpleDocTemplate(outpath, pagesize=A4,
                            leftMargin=MARGIN, rightMargin=MARGIN,
                            topMargin=top_margin, bottomMargin=MARGIN,
                            title=f"CV - {data.get('full_name','')}")
    if on_page:
        doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    elif watermark:
        doc.build(story, onFirstPage=_wm_only, onLaterPages=_wm_only)
    else:
        doc.build(story)
    return outpath


def generate_preview(data, lang, design, png_path, photo_path=None):
    """Safe preview: masked contact + watermark + low-res PNG. No extractable files."""
    import tempfile
    masked = mask_contact(data)
    tmp = tempfile.mktemp(suffix='.pdf', dir=os.path.expanduser('~/tmp'))
    try:
        generate_pdf(masked, lang, design, tmp, watermark=True,
                     photo_path=photo_path)
        pdf_first_page_png(tmp, png_path, dpi=72)
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass
    return png_path

# ================= DOCX (dependency-free, see docxgen.py) =================
from docxgen import DocxBuilder

def _d_para(b, text, lang, size=11, bold=False, align=None, color=None,
            space_after=4, shade=None, border_bottom=None):
    b.para(text, size=size, bold=bold, align=align, color=color,
           space_after=space_after, shade=shade, border_bottom=border_bottom)

def _docx_sections(b, lang, d, accent=None):
    acc = accent or '000000'
    if d.get('summary'):
        _d_para(b, L[lang]['summary'], lang, 13, True, color=acc)
        _d_para(b, d['summary'], lang, 10.5)
    exps = d.get('experience') or []
    if exps:
        _d_para(b, L[lang]['experience'], lang, 13, True, color=acc)
        for e in exps:
            head = f"{e.get('title','')} — {e.get('company','')}"
            _d_para(b, head, lang, 11, True, space_after=1)
            if e.get('period'):
                _d_para(b, e['period'], lang, 9.5, color='646464', space_after=2)
            for line in [l.strip() for l in (e.get('desc') or '').split('\n') if l.strip()]:
                _d_para(b, f'• {line}', lang, 10.5, space_after=2)
    if d.get('education'):
        _d_para(b, L[lang]['education'], lang, 13, True, color=acc)
        for line in [l.strip() for l in d['education'].split('\n') if l.strip()]:
            _d_para(b, line, lang, 10.5)
    certs = d.get('certs') or []
    if certs:
        _d_para(b, L[lang]['certs'], lang, 13, True, color=acc)
        for c in certs:
            _d_para(b, f'• {c}', lang, 10.5, space_after=2)
    skills = d.get('skills') or []
    if skills:
        _d_para(b, L[lang]['skills'], lang, 13, True, color=acc)
        _d_para(b, ' • '.join(skills), lang, 10.5)
    langs = d.get('languages') or []
    if langs:
        _d_para(b, L[lang]['languages'], lang, 13, True, color=acc)
        _d_para(b, ' • '.join(langs), lang, 10.5)

def generate_docx(data, lang, design, outpath):
    b = DocxBuilder(lang)
    ctr = 'center'
    if design == 'modern':
        _d_para(b, data.get('full_name', ''), lang, 20, True, align=ctr,
                color='FFFFFF', space_after=2, shade='16161F')
        if data.get('job_title'):
            _d_para(b, data['job_title'], lang, 11, align=ctr,
                    color='CFCFD8', shade='16161F')
        accent = '16161F'
        hr = ('16161F', 6)
    elif design == 'medical':
        _d_para(b, data.get('full_name', ''), lang, 20, True, color='0A5E5D')
        if data.get('job_title'):
            _d_para(b, data['job_title'], lang, 11.5, color='333333')
        accent = '0A5E5D'
        hr = ('0E7C7B', 10)
    elif design in ('modern_executive', 'modern_professional'):
        _d_para(b, data.get('full_name', ''), lang, 20, True, align=ctr,
                color='FFFFFF', space_after=2, shade='2C3E50')
        if data.get('job_title'):
            _d_para(b, data['job_title'], lang, 11.5, align=ctr,
                    color='FFFFFF', shade='2C3E50')
        accent = '2C3E50'
        hr = ('2C3E50', 8)
    else:
        _d_para(b, data.get('full_name', ''), lang, 19, True, align=ctr)
        if data.get('job_title'):
            _d_para(b, data['job_title'], lang, 11.5, align=ctr, color='444444')
        accent = '000000'
        hr = ('222222', 6)

    parts = [p for p in [data.get('phone', ''), data.get('email', ''),
                         data.get('address', '')] if p]
    _d_para(b, '  |  '.join(parts), lang, 9, align=ctr, color='555555',
            border_bottom=hr, space_after=8)
    _docx_sections(b, lang, data, accent=accent)
    b.save(outpath)
    return outpath

# ---------- preview ----------
def pdf_first_page_png(pdf_path, png_path, dpi=110):
    try:
        import fitz
        doc = fitz.open(pdf_path)
        pix = doc[0].get_pixmap(dpi=dpi)
        pix.save(png_path)
        doc.close()
        return png_path
    except ImportError:
        pass
    import subprocess
    subprocess.run(['pdftoppm', '-png', '-r', str(dpi), '-f', '1', '-l', '1',
                    '-singlefile', pdf_path, png_path.replace('.png', '')],
                   check=True)
    return png_path
