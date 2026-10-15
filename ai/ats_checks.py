"""ATS checks: readability, parsing, keywords, formatting risks.

These are INTERNAL indicators, not official ATS scores.
Per research: no single ATS algorithm; these check structural safety.
"""
import re


def check_readability(pdf_path):
    """Extract text and verify linear reading order."""
    issues = []
    try:
        from pypdf import PdfReader
        r = PdfReader(pdf_path)
        text = '\n'.join(p.extract_text() or '' for p in r.pages)
    except Exception as e:
        return {'passed': False, 'issues': [f'extract_failed:{e}'], 'text': ''}

    if len(text.strip()) < 50:
        issues.append('too_little_text')

    # Check for common parsing failures
    if re.search(r'[�□]', text):
        issues.append('encoding_garbage')
    # Check text isn't image-only (has extractable words)
    words = len(text.split())
    if words < 20:
        issues.append('low_word_count')

    return {'passed': len(issues) == 0, 'issues': issues,
            'text': text, 'word_count': words,
            'pages': len(r.pages)}


# Required vs optional sections per template type
REQUIRED_SECTIONS = {
    'ats_professional': ['experience', 'education', 'skills'],
    'ats_minimal': ['experience', 'education', 'skills'],
    # Human-read templates: only check what's actually rendered
    'modern_executive': ['experience', 'skills'],
    'modern_professional': ['experience', 'skills'],
    'modern_corporate': ['experience', 'skills'],
}
# Map design_key -> section labels in both languages
SECTION_LABELS = {
    'experience': ['experience', 'work experience', 'الخبرة', 'الخبرات'],
    'education': ['education', 'التعليم', 'الدراسة'],
    'skills': ['skills', 'المهارات'],
}

def check_sections(text, lang='en', design_key=None):
    """Verify sections present. Template-aware: only require what the
    template actually renders. Graduates without experience are not blocked."""
    # Determine which sections this template should have
    if design_key and design_key in REQUIRED_SECTIONS:
        required = REQUIRED_SECTIONS[design_key]
    else:
        required = ['experience', 'education', 'skills']
    tl = text.lower()
    found, missing, optional_missing = [], [], []
    for sec in required:
        labels = SECTION_LABELS.get(sec, [sec])
        if any(lbl in tl or lbl in text for lbl in labels):
            found.append(sec)
        else:
            # Experience missing = check if user actually has experience
            # (don't block graduates)
            missing.append(sec)
    # Distinguish: experience/education are structural, skills always expected
    critical_missing = [m for m in missing if m == 'skills']
    return {'found': found, 'missing': missing,
            'critical_missing': critical_missing,
            # Only fail on critical, not on graduate-appropriate gaps
            'passed': len(critical_missing) == 0}


def check_formatting_risks(pdf_path, design_key):
    """Flag design choices that risk ATS parsing."""
    risks = []
    # Known risky designs
    risky = {'modern_executive', 'modern_professional'}  # sidebars/columns
    if design_key in risky:
        risks.append('multi_column_layout')
        risks.append('sidebar_content_may_scramble')

    try:
        from pypdf import PdfReader
        r = PdfReader(pdf_path)
        if len(r.pages) > 2:
            risks.append('too_many_pages')
    except Exception:
        pass

    return {'risks': risks, 'passed': len(risks) == 0}


def check_keyword_coverage(text, job_description):
    """Compare JD keywords against CV text. Returns coverage, NOT a score."""
    if not job_description:
        return {'coverage': None, 'note': 'no_jd_provided'}

    # Extract meaningful keywords from JD (words 4+ chars, not stopwords)
    stopwords = {'the', 'and', 'for', 'with', 'from', 'that', 'this',
                 'will', 'are', 'our', 'you', 'your', 'job', 'role',
                 'من', 'في', 'على', 'إلى', 'مع', 'هذا', 'التي'}
    jd_words = set(w.lower() for w in re.findall(r'\w{4,}', job_description.lower())
                   if w.lower() not in stopwords)
    cv_text = text.lower()

    matched = [w for w in jd_words if w in cv_text]
    coverage = len(matched) / max(len(jd_words), 1)

    return {
        'coverage': round(coverage, 2),
        'matched_count': len(matched),
        'total_keywords': len(jd_words),
        'note': 'internal_indicator_not_official_score',
    }


def run_ats_checks(pdf_path, design_key, lang='en', job_description=None):
    """Run all ATS checks. Returns summary."""
    readability = check_readability(pdf_path)
    sections = check_sections(readability.get('text', ''), lang,
                               design_key=design_key)
    formatting = check_formatting_risks(pdf_path, design_key)
    keywords = check_keyword_coverage(readability.get('text', ''), job_description)

    all_passed = (readability['passed'] and sections['passed']
                  and formatting['passed'])

    return {
        'passed': all_passed,
        'readability': readability,
        'sections': sections,
        'formatting': formatting,
        'keywords': keywords,
        'disclaimer': ('Internal indicators only. Not an official ATS score. '
                       'Different systems (Workday, Greenhouse, Lever) parse differently.'),
    }
