"""Old CV import — extract text from PDF/DOCX/photo for review & reuse."""
import io
import os
import logging
import re

log = logging.getLogger('cvbot')

EMAIL_RE = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
PHONE_RE = re.compile(r'(\+?\d[\d\s\-()]{6,}\d)')


def _extract_pdf_pypdf(data: bytes) -> str:
    """Primary PDF extractor: pypdf (pure-python, installed)."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        reader = PdfReader(io.BytesIO(data))
        parts = [(p.extract_text() or "") for p in reader.pages]
        return "\n".join(parts).strip()
    except Exception as e:
        log.warning("pdf extract via pypdf failed: %s", e)
        return ""


def _extract_pdf_fitz(data: bytes) -> str:
    """Secondary PDF extractor: PyMuPDF (better layout, optional)."""
    try:
        import fitz
    except ImportError:
        return ""
    try:
        doc = fitz.open(stream=data, filetype="pdf")
        parts = [page.get_text() for page in doc]
        doc.close()
        return "\n".join(parts).strip()
    except Exception as e:
        log.warning("pdf extract via fitz failed: %s", e)
        return ""


_PRES_RE = re.compile(r'[\ufb50-\ufdff\ufe70-\ufeff]')


_BIDI_MARKS_RE = re.compile('[‪‫‬‭‮⁦⁧⁨⁩‬‎‏﻿]')


def _normalize_extracted_arabic(text):
    """Normalize extractor output to clean logical-order text.

    pdftotext returns shaped glyphs in logical order wrapped in BiDi
    marks; pypdf returns shaped logical-order text as well. Strip the
    marks and NFKC presentation forms back to base letters. No
    reordering is needed (and none is done): the extractors already
    yield logical order. Text without presentation forms passes through
    unchanged apart from mark stripping.
    """
    import unicodedata
    if not text:
        return ''
    text = _BIDI_MARKS_RE.sub('', text)
    if _PRES_RE.search(text):
        text = unicodedata.normalize('NFKC', text)
    return text


def _extract_pdf_pdftotext(data):
    """Primary PDF extractor: pdftotext (poppler) - logical order output."""
    import shutil
    import subprocess
    import tempfile
    if not shutil.which('pdftotext'):
        return ''
    tmpdir = os.path.expanduser('~/tmp')
    try:
        os.makedirs(tmpdir, exist_ok=True)
    except Exception:
        pass
    path = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.pdf', dir=tmpdir,
                                         delete=False) as f:
            f.write(data)
            path = f.name
        out = subprocess.run(['pdftotext', path, '-'], capture_output=True,
                             timeout=60)
        if out.returncode != 0:
            return ''
        return out.stdout.decode('utf-8', 'ignore').strip()
    except Exception as e:
        log.warning('pdf extract via pdftotext failed: %s', e)
        return ''
    finally:
        if path:
            try:
                os.remove(path)
            except Exception:
                pass


def extract_pdf_text(data):
    """Extract text from PDF bytes: pdftotext, pypdf, then PyMuPDF.

    Returns '' when no extractor is available or the file is unreadable;
    the caller shows a graceful message - never invents content.
    """
    for _fn in (_extract_pdf_pdftotext, _extract_pdf_pypdf, _extract_pdf_fitz):
        text = _fn(data)
        if text:
            return _normalize_extracted_arabic(text)
    return ''

def _extract_docx_stdlib(data: bytes) -> str:
    """Dependency-free DOCX extractor (python-docx/lxml won't build on Termux).

    DOCX is a zip; text lives in w:t elements inside w:p paragraphs
    (table cells contain w:p too, so document order is preserved).
    """
    import zipfile
    import xml.etree.ElementTree as ET
    W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        xml_bytes = z.read('word/document.xml')
    except Exception as e:
        log.warning('docx unzip/read failed: %s', e)
        return ''
    try:
        root = ET.fromstring(xml_bytes)
    except Exception as e:
        log.warning('docx xml parse failed: %s', e)
        return ''
    parts = []
    for p in root.iter(W + 'p'):
        para = ''.join((t.text or '') for t in p.iter(W + 't')).strip()
        if para:
            parts.append(para)
    return '\n'.join(parts).strip()


def extract_docx_text(data: bytes) -> str:
    """Extract text from DOCX bytes: stdlib parser first, python-docx fallback."""
    text = _extract_docx_stdlib(data)
    if text:
        return text
    try:
        from docx import Document
    except ImportError:
        return ''
    try:
        doc = Document(io.BytesIO(data))
        parts = [p.text for p in doc.paragraphs]
        for table in doc.tables:
            for row in table.rows:
                parts.append(' | '.join(c.text for c in row.cells))
        return '\n'.join(p for p in parts if p.strip()).strip()
    except Exception as e:
        log.warning('docx extract via python-docx failed: %s', e)
        return ''


def parse_fields(text: str) -> dict:
    """Heuristic field extraction. Returns {field: (value, confidence)}.
    confidence: 'confirmed' | 'review'"""
    fields = {}
    if not text:
        return fields

    emails = EMAIL_RE.findall(text)
    if emails:
        fields['email'] = (emails[0], 'confirmed')

    phones = PHONE_RE.findall(text)
    if phones:
        # prefer longest plausible
        best = max(phones, key=len)
        fields['phone'] = (best.strip(), 'review')

    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if lines:
        # first non-empty short line is likely the name
        for ln in lines[:5]:
            if len(ln) < 60 and not EMAIL_RE.search(ln) and not PHONE_RE.search(ln):
                fields['full_name'] = (ln, 'review')
                break

    # naive section detection
    section_kw = {
        'experience': ['experience', 'خبرة', 'الخبرة', 'work history', 'employment'],
        'education': ['education', 'تعليم', 'التعليم', 'university', 'جامعة', 'college'],
        'skills': ['skills', 'مهارات', 'المهارات'],
        'certs': ['certif', 'شهادات', 'دورات', 'courses'],
        'summary': ['summary', 'objective', 'ملخص', 'نبذة'],
    }
    low = text.lower()
    found_sections = []
    for key, kws in section_kw.items():
        if any(k in low for k in kws):
            found_sections.append(key)
    if found_sections:
        fields['detected_sections'] = (', '.join(found_sections), 'review')

    fields['raw_text'] = (text[:4000], 'confirmed')
    return fields


def extract_from_file(data: bytes, filename: str = '') -> dict:
    """Dispatch by extension. Returns {'text': str, 'kind': str}."""
    fn = (filename or '').lower()
    if fn.endswith('.pdf'):
        return {'text': extract_pdf_text(data), 'kind': 'pdf'}
    if fn.endswith('.docx') or fn.endswith('.doc'):
        return {'text': extract_docx_text(data), 'kind': 'docx'}
    return {'text': '', 'kind': 'unknown'}


def format_review(fields: dict, lang='ar') -> str:
    """Format extracted fields for user review with confidence marks."""
    if lang == 'ar':
        lines = ['🔍 *المعلومات المستخرجة من ملفك:*', '']
        labels = {
            'full_name': 'الاسم', 'email': 'الإيميل', 'phone': 'الهاتف',
            'detected_sections': 'أقسام مكتشفة',
        }
        for key, label in labels.items():
            if key in fields:
                val, conf = fields[key]
                mark = '✅' if conf == 'confirmed' else '⚠️ يحتاج مراجعة'
                lines.append(f'{mark} *{label}:* {val[:120]}')
        lines += ['', 'راجع المعلومات وصحّح أي خطأ قبل المتابعة.']
        return '\n'.join(lines)
    lines = ['🔍 *Extracted info from your file:*', '']
    labels = {
        'full_name': 'Name', 'email': 'Email', 'phone': 'Phone',
        'detected_sections': 'Detected sections',
    }
    for key, label in labels.items():
        if key in fields:
            val, conf = fields[key]
            mark = '✅' if conf == 'confirmed' else '⚠️ needs review'
            lines.append(f'{mark} *{label}:* {val[:120]}')
    lines += ['', 'Review and correct any mistakes before continuing.']
    return '\n'.join(lines)
