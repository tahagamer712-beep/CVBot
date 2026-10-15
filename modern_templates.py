"""Modern CV templates — Modern Executive & Modern Professional.

Visual identity derived from reference CVs (Oct 2026):
- Dark navy #2C3E50 + white + black, strong typographic hierarchy
- Executive: sidebar layout (navy sidebar, photo, contact/skills)
- Professional: top banner layout (dark banner, circular photo, ruled sections)
Both support AR/RTL and EN/LTR with proper BiDi via cvgen.visual().
"""
import os

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, Image as RLImage,
                                PageTemplate, Paragraph, Spacer, Table,
                                TableStyle, HRFlowable)
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER

BASE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(BASE, 'fonts')

# NOTE: Cairo TTFs on this device lack Arabic glyphs (tofu). Using Amiri
# (full Arabic coverage) for all text. Layout provides the modern feel.
# Revisit with a complete sans-serif Arabic font when available.

# import BiDi helpers from cvgen (single source of truth)
import cvgen
_v = cvgen._v
visual = cvgen.visual

NAVY = HexColor('#2C3E50')
NAVY_DARK = HexColor('#1A252F')
BLACK = HexColor('#111111')
GRAY = HexColor('#5D6D7E')
LIGHT_GRAY = HexColor('#EAEDED')
WHITE = HexColor('#FFFFFF')
ACCENT = HexColor('#3498DB')

PAGE_W, PAGE_H = A4


def _draw_watermark(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(HexColor('#cc0000'))
    canvas.setFont('Amiri-Bold', 42)
    canvas.rotate(35)
    for y in range(-200, 1100, 220):
        canvas.setFillAlpha(0.10)
        canvas.drawString(60, y, 'PREVIEW - NOT FINAL')
    canvas.restoreState()


def _styles(lang):
    rtl = lang == 'ar'
    align = TA_RIGHT if rtl else TA_LEFT
    return {
        'name_first': ParagraphStyle('m_name_first', fontName='Amiri', fontSize=26,
                                     leading=30, alignment=align, textColor=BLACK),
        'name_last': ParagraphStyle('m_name_last', fontName='Amiri-Bold', fontSize=26,
                                    leading=30, alignment=align, textColor=BLACK),
        'title': ParagraphStyle('m_title', fontName='Amiri-Bold', fontSize=11,
                                leading=14, alignment=align, textColor=WHITE),
        'h2': ParagraphStyle('m_h2', fontName='Amiri-Bold', fontSize=12,
                             leading=15, alignment=align, textColor=NAVY,
                             spaceBefore=10, spaceAfter=4),
        'body': ParagraphStyle('m_body', fontName='Amiri', fontSize=9.5,
                               leading=14, alignment=align, textColor=BLACK,
                               spaceAfter=4),
        'bullet': ParagraphStyle('m_bullet', fontName='Amiri', fontSize=9.5,
                                 leading=14, alignment=align, textColor=BLACK,
                                 leftIndent=12 if not rtl else 0,
                                 rightIndent=12 if rtl else 0,
                                 spaceAfter=2),
        'jobhead': ParagraphStyle('m_jobhead', fontName='Amiri-Bold', fontSize=10.5,
                                  leading=14, alignment=align, textColor=BLACK,
                                  spaceBefore=6),
        'period': ParagraphStyle('m_period', fontName='Amiri', fontSize=9,
                                 leading=12, alignment=align, textColor=GRAY),
        # sidebar styles (always LTR-aligned within sidebar, text via visual())
        'sb_h': ParagraphStyle('sb_h', fontName='Amiri-Bold', fontSize=11,
                               leading=14, alignment=TA_CENTER, textColor=WHITE,
                               spaceBefore=12, spaceAfter=6),
        'sb_body': ParagraphStyle('sb_body', fontName='Amiri', fontSize=8.5,
                                  leading=12, alignment=TA_CENTER, textColor=WHITE,
                                  spaceAfter=2),
        'sb_bullet': ParagraphStyle('sb_bullet', fontName='Amiri', fontSize=8.5,
                                    leading=12, alignment=TA_CENTER,
                                    textColor=WHITE, spaceAfter=2),
    }


def _split_name(full_name, lang):
    """Split name into first (light) + rest (bold)."""
    parts = (full_name or '').strip().split()
    if len(parts) >= 2:
        return parts[0], ' '.join(parts[1:])
    return full_name or '', ''


def _draw_circle_photo(canvas, photo_path, cx, cy, r):
    if not photo_path or not os.path.exists(photo_path):
        return False
    try:
        canvas.saveState()
        p = canvas.beginPath()
        p.circle(cx, cy, r)
        canvas.clipPath(p, stroke=0, fill=0)
        canvas.drawImage(photo_path, cx - r, cy - r, width=2 * r, height=2 * r,
                         preserveAspectRatio=True, anchor='c')
        canvas.restoreState()
        return True
    except Exception:
        try:
            canvas.restoreState()
        except Exception:
            pass
        return False


# ================= MODERN EXECUTIVE =================
def generate_executive(data, lang, outpath, photo_path=None, watermark=False):
    """Sidebar layout: navy sidebar (photo/contact/skills) + main column."""
    rtl = lang == 'ar'
    styles = _styles(lang)
    sb_w = PAGE_W * 0.36
    margin = 18

    if rtl:
        sb_x = 0
        main_x = sb_w + 10
        main_w = PAGE_W - sb_w - 10 - margin
    else:
        sb_x = PAGE_W - sb_w
        main_x = margin
        main_w = PAGE_W - sb_w - 10 - margin

    story = []
    S = styles

    # ---- name ----
    first, rest = _split_name(data.get('full_name', ''), lang)
    story.append(Paragraph(_v(first, lang), S['name_first']))
    if rest:
        story.append(Paragraph(_v(rest, lang), S['name_last']))
    story.append(Spacer(1, 6))

    # ---- title ribbon ----
    if data.get('job_title'):
        ribbon_data = [[Paragraph(_v(data['job_title'], lang), S['title'])]]
        ribbon = Table(ribbon_data, colWidths=[main_w])
        ribbon.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), NAVY),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING', (0, 0), (-1, -1), 12),
            ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ]))
        story.append(ribbon)
        story.append(Spacer(1, 10))

    # ---- sections ----
    def section(key):
        story.append(Paragraph(_v(cvgen.L[lang][key], lang), S['h2']))
        story.append(HRFlowable(width='100%', thickness=1, color=NAVY,
                                spaceAfter=6, spaceBefore=2))

    if data.get('summary'):
        section('summary')
        story.append(Paragraph(_v(data['summary'], lang), S['body']))
    exps = data.get('experience') or []
    if exps:
        section('experience')
        for e in exps:
            head = "%s — %s" % (e.get('title', ''), e.get('company', ''))
            story.append(Paragraph(_v(head, lang), S['jobhead']))
            if e.get('period'):
                story.append(Paragraph(_v(e['period'], lang), S['period']))
            for line in [l.strip() for l in (e.get('desc') or '').split('\n') if l.strip()]:
                story.append(Paragraph(_v('• ' + line, lang), S['bullet']))
    if data.get('education'):
        section('education')
        edu = data['education']
        if isinstance(edu, list):
            for e in edu:
                story.append(Paragraph(_v(str(e), lang), S['body']))
        else:
            story.append(Paragraph(_v(str(edu), lang), S['body']))
    certs = data.get('certs') or []
    if certs:
        if isinstance(certs, str):
            certs = [c.strip() for c in certs.split('\n') if c.strip()]
        section('certs')
        for c in certs:
            story.append(Paragraph(_v('• ' + str(c), lang), S['bullet']))

    # ---- sidebar painter (drawn on every page) ----
    def sidebar(canv, doc):
        canv.saveState()
        # sidebar background
        canv.setFillColor(NAVY)
        canv.rect(sb_x, 0, sb_w, PAGE_H, stroke=0, fill=1)
        # photo
        photo_cx = sb_x + sb_w / 2
        photo_cy = PAGE_H - 80
        photo_r = 52
        # photo ring
        canv.setStrokeColor(WHITE)
        canv.setLineWidth(3)
        canv.circle(photo_cx, photo_cy, photo_r + 4, stroke=1, fill=0)
        _draw_circle_photo(canv, photo_path, photo_cx, photo_cy, photo_r)
        canv.restoreState()
        # sidebar text via platypus in a frame
        sb_story = []
        # contact
        contact_label = 'معلومات التواصل' if lang == 'ar' else 'Contact'
        sb_story.append(Paragraph(_v(contact_label, lang), S['sb_h']))
        for key in ('phone', 'email', 'address'):
            val = data.get(key, '')
            if val:
                sb_story.append(Paragraph(_v(val, lang), S['sb_body']))
        sb_story.append(Spacer(1, 6))
        skills = data.get('skills') or []
        if isinstance(skills, str):
            skills = [s.strip() for s in skills.split('\n') if s.strip()]
        if skills:
            sb_story.append(Paragraph(_v(cvgen.L[lang]['skills'], lang), S['sb_h']))
            for s in skills[:12]:
                sb_story.append(Paragraph(_v('• ' + str(s), lang), S['sb_bullet']))
        langs = data.get('languages') or []
        if isinstance(langs, str):
            langs = [l.strip() for l in langs.split('\n') if l.strip()]
        if langs:
            sb_story.append(Paragraph(_v(cvgen.L[lang]['languages'], lang), S['sb_h']))
            for lg in langs:
                sb_story.append(Paragraph(_v(str(lg), lang), S['sb_body']))
        sb_frame = Frame(sb_x + 10, 30, sb_w - 20, PAGE_H - 170,
                         leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        sb_frame.addFromList(sb_story, canv)

    doc = BaseDocTemplate(outpath, pagesize=A4,
                          leftMargin=main_x, rightMargin=PAGE_W - main_x - main_w,
                          topMargin=36, bottomMargin=36)
    main_frame = Frame(main_x, 36, main_w, PAGE_H - 72,
                       leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    def _exec_page(canv, d):
        sidebar(canv, d)
        if watermark:
            _draw_watermark(canv, d)
    # sidebar drawn on every page via onPage
    doc.addPageTemplates([PageTemplate(id='exec', frames=[main_frame],
                                       onPage=_exec_page)])
    doc.build(story)
    return outpath


# ================= MODERN PROFESSIONAL =================
def generate_professional(data, lang, outpath, photo_path=None, watermark=False):
    """Top banner layout: dark banner (photo/name/title) + ruled single column."""
    rtl = lang == 'ar'
    styles = _styles(lang)
    S = styles
    margin = 36
    banner_h = 130

    story = []

    def banner(canv, doc):
        canv.saveState()
        # banner background
        canv.setFillColor(NAVY_DARK)
        canv.rect(0, PAGE_H - banner_h, PAGE_W, banner_h, stroke=0, fill=1)
        # photo circle
        photo_r = 42
        if rtl:
            photo_cx = PAGE_W - margin - photo_r
        else:
            photo_cx = margin + photo_r
        photo_cy = PAGE_H - banner_h / 2
        canv.setStrokeColor(WHITE)
        canv.setLineWidth(2.5)
        canv.circle(photo_cx, photo_cy, photo_r + 3, stroke=1, fill=0)
        _draw_circle_photo(canv, photo_path, photo_cx, photo_cy, photo_r)
        # name + title in banner
        tx = margin + (2 * photo_r + 24) if not rtl else None
        if rtl:
            tx_right = PAGE_W - margin - (2 * photo_r + 24)
        canv.setFillColor(WHITE)
        name = data.get('full_name', '')
        title = data.get('job_title', '')
        if rtl:
            canv.setFont('Amiri-Bold', 22)
            canv.drawRightString(tx_right, PAGE_H - 62, visual(name, base_rtl=True))
            if title:
                canv.setFont('Amiri', 11)
                # letter-spacing simulation for title
                canv.drawRightString(tx_right, PAGE_H - 86, visual(title, base_rtl=True))
        else:
            canv.setFont('Amiri-Bold', 22)
            canv.drawString(tx, PAGE_H - 70, name)
            if title:
                canv.setFont('Amiri', 11)
                canv.drawString(tx, PAGE_H - 92, title.upper())
        canv.restoreState()

    def contact_bar(canv, doc):
        # drawn as part of story (not banner) — simple text line
        pass

    # contact bar (in flow, below banner)
    contact_parts = [data.get('phone', ''), data.get('email', ''), data.get('address', '')]
    contact_parts = [p for p in contact_parts if p]
    if contact_parts:
        cstyle = ParagraphStyle('pro_contact', fontName='Amiri', fontSize=8.5,
                                leading=12, alignment=TA_CENTER, textColor=GRAY,
                                spaceAfter=4, spaceBefore=6)
        story.append(Paragraph(_v('  |  '.join(contact_parts), lang), cstyle))
        story.append(HRFlowable(width='100%', thickness=0.8, color=LIGHT_GRAY,
                                spaceAfter=8, spaceBefore=4))

    def section(key):
        story.append(Paragraph(_v(cvgen.L[lang][key], lang), S['h2']))
        story.append(HRFlowable(width='100%', thickness=1, color=NAVY,
                                spaceAfter=6, spaceBefore=2))

    if data.get('summary'):
        section('summary')
        story.append(Paragraph(_v(data['summary'], lang), S['body']))
    skills = data.get('skills') or []
    if isinstance(skills, str):
        skills = [s.strip() for s in skills.split('\n') if s.strip()]
    if skills:
        section('skills')
        # 3-column skills table
        cols = 3
        rows = []
        for i in range(0, len(skills), cols):
            chunk = skills[i:i + cols]
            while len(chunk) < cols:
                chunk.append('')
            rows.append([Paragraph(_v('• ' + s, lang) if s else '', S['bullet'])
                         for s in chunk])
        # for RTL, reverse column order
        if rtl:
            rows = [[c for c in reversed(r)] for r in rows]
        t = Table(rows, colWidths=[(PAGE_W - 2 * margin) / cols] * cols)
        t.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'),
                               ('TOPPADDING', (0, 0), (-1, -1), 2),
                               ('BOTTOMPADDING', (0, 0), (-1, -1), 2)]))
        story.append(t)
        story.append(Spacer(1, 4))
    exps = data.get('experience') or []
    if exps:
        section('experience')
        for e in exps:
            # title left, period right (mirrored for RTL)
            head_t = "%s — %s" % (e.get('title', ''), e.get('company', ''))
            prow = [Paragraph(_v(head_t, lang), S['jobhead']),
                    Paragraph(_v(e.get('period', ''), lang), S['period'])]
            if rtl:
                prow = prow[::-1]
            t = Table([prow], colWidths=[PAGE_W - 2 * margin - 110, 110])
            t.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')]))
            story.append(t)
            for line in [l.strip() for l in (e.get('desc') or '').split('\n') if l.strip()]:
                story.append(Paragraph(_v('• ' + line, lang), S['bullet']))
    if data.get('education'):
        section('education')
        edu = data['education']
        if isinstance(edu, list):
            for e_item in edu:
                story.append(Paragraph(_v(str(e_item), lang), S['body']))
        else:
            story.append(Paragraph(_v(str(edu), lang), S['body']))
    certs = data.get('certs') or []
    if isinstance(certs, str):
        certs = [c.strip() for c in certs.split('\n') if c.strip()]
    if certs:
        section('certs')
        for c in certs:
            story.append(Paragraph(_v('• ' + str(c), lang), S['bullet']))
    langs = data.get('languages') or []
    if isinstance(langs, str):
        langs = [l.strip() for l in langs.split('\n') if l.strip()]
    if langs:
        section('languages')
        story.append(Paragraph(_v('  •  '.join(langs), lang), S['body']))

    doc = BaseDocTemplate(outpath, pagesize=A4,
                          leftMargin=margin, rightMargin=margin,
                          topMargin=banner_h + 12, bottomMargin=36)

    def on_page(canv, d):
        if watermark:
            _draw_watermark(canv, d)
        if d.page == 1:
            banner(canv, d)
        else:
            # slim header on later pages
            canv.saveState()
            canv.setFillColor(NAVY_DARK)
            canv.rect(0, PAGE_H - 44, PAGE_W, 44, stroke=0, fill=1)
            canv.setFillColor(WHITE)
            canv.setFont('Amiri-Bold', 10)
            nm = data.get('full_name', '')
            if rtl:
                canv.drawRightString(PAGE_W - margin, PAGE_H - 30,
                                     visual(nm, base_rtl=True))
            else:
                canv.drawString(margin, PAGE_H - 30, nm)
            canv.restoreState()

    frame = Frame(margin, 36, PAGE_W - 2 * margin, PAGE_H - banner_h - 48,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    # for pages 2+, we need a taller frame; use two templates
    frame2 = Frame(margin, 36, PAGE_W - 2 * margin, PAGE_H - 80,
                   leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([
        PageTemplate(id='pro1', frames=[frame], onPage=on_page),
        PageTemplate(id='pro2', frames=[frame2], onPage=on_page),
    ])
    # build with manual page template switching
    doc.build(story)
    return outpath
