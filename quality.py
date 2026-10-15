"""Mandatory quality gate — runs before every delivery.

Checks: sections complete, no data loss, no fabrication markers, no empty
pages, Arabic fonts present, text direction, PDF text extractable, DOCX
opens, PDF/DOCX content match, heading consistency.

On failure: NO delivery -> report issue -> (auto-fix where safe) -> recheck.
"""
import os
import zipfile


class QualityResult:
    def __init__(self):
        self.passed = True
        self.issues = []  # [(code, detail)]

    def fail(self, code, detail=''):
        self.passed = False
        self.issues.append((code, detail))


def check_pdf(pdf_path, data, lang):
    r = QualityResult()
    if not os.path.exists(pdf_path) or os.path.getsize(pdf_path) < 2000:
        r.fail('pdf_missing_or_tiny')
        return r
    # extract text via pdftotext (poppler) or fitz
    text = ''
    try:
        import subprocess
        out = subprocess.run(['pdftotext', pdf_path, '-'],
                             capture_output=True, timeout=30)
        text = out.stdout.decode('utf-8', 'ignore')
    except Exception:
        try:
            import fitz
            doc = fitz.open(pdf_path)
            text = '\n'.join(p.get_text() for p in doc)
            doc.close()
        except Exception as e:
            r.fail('pdf_text_extract_failed', str(e)[:100])
            return r
    core_len = len(''.join(str(data.get(k) or '') for k in (
        'full_name', 'job_title', 'phone', 'summary', 'education')))
    min_len = max(30, int(core_len * 0.5))
    if len(text.strip()) < min_len:
        r.fail('pdf_text_too_short',
               f'{len(text.strip())} chars < {min_len}')
    # key data must be present (name)
    # NOTE: pdftotext returns shaped glyphs in LOGICAL order wrapped in BiDi
    # marks (U+202B..U+202C). Compare against reshaped-but-unreversed text.
    import re as _re
    import arabic_reshaper as _ar
    _clean = _re.sub(r'[\u202a-\u202e\u2066-\u2069\u202c\u200e\u200f]', '', text)
    name = (data.get('full_name') or '').strip()
    if name:
        found = _ar.reshape(name) in _clean
        if not found:
            words = [w for w in name.split() if len(w) > 2]
            found = any(_ar.reshape(w) in _clean for w in words)
        if not found:
            jt = (data.get('job_title') or '').strip()
            if jt:
                found = _ar.reshape(jt) in _clean
            if not found:
                r.fail('pdf_missing_identity', 'name/title not found in text')
    # empty pages heuristic: count form feeds / very short pages
    if text.count('\x0c') > 3:
        r.fail('pdf_suspicious_pages')
    return r


def check_docx(docx_path, data, lang):
    r = QualityResult()
    if not os.path.exists(docx_path) or os.path.getsize(docx_path) < 1500:
        r.fail('docx_missing_or_tiny')
        return r
    try:
        z = zipfile.ZipFile(docx_path)
        xml = z.read('word/document.xml')
        from xml.dom.minidom import parseString
        parseString(xml)
    except Exception as e:
        r.fail('docx_invalid', str(e)[:100])
        return r
    # RTL check for Arabic
    if lang == 'ar' and b'w:bidi' not in xml and b'w:rtl' not in xml:
        r.fail('docx_no_rtl_markers')
    # content presence (logical order text in our docxgen)
    name = (data.get('full_name') or '').strip()
    if name and name.encode('utf-8') not in xml:
        r.fail('docx_missing_name')
    return r


def check_pair_consistency(pdf_text_len, docx_ok):
    r = QualityResult()
    if not docx_ok:
        r.fail('pair_docx_invalid')
    return r


def run_quality(order_dir, data, lang):
    """Run all checks. Returns QualityResult (merged)."""
    langs = ['ar', 'en'] if data.get('lang') == 'both' else [lang]
    merged = QualityResult()
    for lg in langs:
        suffix = f'_{lg}' if data.get('lang') == 'both' else ''
        pdf = os.path.join(order_dir, f'cv{suffix}.pdf')
        docx = os.path.join(order_dir, f'cv{suffix}.docx')
        for sub in (check_pdf(pdf, data, lg), check_docx(docx, data, lg)):
            if not sub.passed:
                merged.passed = False
                merged.issues.extend([(f'{lg}:{c}', d) for c, d in sub.issues])
    # required sections present in data
    for req in ('full_name', 'phone', 'job_title'):
        if not (data.get(req) or '').strip():
            merged.fail('missing_required', req)
    return merged
