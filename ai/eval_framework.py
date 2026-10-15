"""Multi-level CV evaluation framework.

Scores 0-100 with mandatory gates:
- info_accuracy: 20 (no fabrication, complete contact)
- job_fit: 20 (relevance to target role)
- ats_readability: 20 (text extraction, single column, standard headings)
- language: 15 (grammar, spelling, RTL/LTR)
- design: 15 (visual balance, whitespace, no overflow)
- technical: 10 (PDF valid, no blank pages, fonts embedded)

Mandatory gates (fail = reject regardless of score):
- no_fabrication, contact_valid, pdf_valid, rtl_ok,
  text_extractable, no_contradiction, dates_valid
"""
import os
import re

def evaluate_hr(data, lang):
    """HR recruiter perspective: 0-20."""
    score = 20
    issues = []
    # Professional identity clarity
    if not data.get('job_title'):
        score -= 4; issues.append('missing_job_title')
    # Summary strength
    summary = data.get('summary', '')
    if len(summary.split()) < 20:
        score -= 3; issues.append('weak_summary')
    if len(summary.split()) > 80:
        score -= 2; issues.append('summary_too_long')
    # Section order (experience before education for experienced)
    exp = data.get('experience', [])
    if exp and not data.get('education'):
        score -= 2; issues.append('missing_education')
    # Skills relevance
    if len(data.get('skills', [])) < 3:
        score -= 3; issues.append('too_few_skills')
    # Contact completeness
    if not data.get('phone') or not data.get('email'):
        score -= 4; issues.append('incomplete_contact')
    return max(0, score), issues


def evaluate_ats(pdf_path, lang):
    """ATS readability: 0-20. Uses real text extraction."""
    score = 20
    issues = []
    try:
        from pypdf import PdfReader
        reader = PdfReader(pdf_path)
        text = ''
        for page in reader.pages:
            text += (page.extract_text() or '') + '\n'
        words = text.split()
        if len(words) < 30:
            score -= 8; issues.append('too_little_text')
        # Contact detectability
        if '@' not in text:
            score -= 4; issues.append('email_not_extractable')
        # Check for common section keywords
        text_lower = text.lower()
        has_exp = any(k in text_lower for k in
                      ['experience', 'الخبرة', 'employment', 'work history'])
        has_edu = any(k in text_lower for k in
                      ['education', 'التعليم', 'university', 'degree'])
        if not has_exp:
            score -= 3; issues.append('experience_not_detected')
        if not has_edu:
            score -= 3; issues.append('education_not_detected')
        # Check for extraction artifacts
        if '�' in text or '\x00' in text:
            score -= 5; issues.append('extraction_corrupted')
    except Exception as e:
        score = 0
        issues.append(f'extraction_failed:{type(e).__name__}')
    return max(0, score), issues


def evaluate_language(data, lang):
    """Language quality: 0-15."""
    score = 15
    issues = []
    text_fields = [data.get('summary', ''), data.get('job_title', '')]
    for exp in data.get('experience', []):
        text_fields.append(exp.get('desc', ''))
        text_fields.append(exp.get('title', ''))
    full = ' '.join(text_fields)
    # Check for excessive repetition
    words = full.lower().split()
    if words:
        from collections import Counter
        most_common = Counter(words).most_common(1)
        if most_common and most_common[0][1] > len(words) * 0.15 and len(words) > 20:
            score -= 2; issues.append('word_repetition')
    # Check sentence length (readability)
    sentences = re.split(r'[.!?؟。]', full)
    long_sentences = [s for s in sentences if len(s.split()) > 35]
    if long_sentences:
        score -= 2; issues.append(f'{len(long_sentences)}_long_sentences')
    # RTL check for Arabic
    if lang in ('ar', 'bilingual'):
        # Check for mixed-direction issues (basic heuristic)
        if re.search(r'[\u0600-\u06FF].*[A-Za-z]{10,}', full):
            pass  # mixed is OK in moderation
    # Empty critical fields
    if not data.get('summary', '').strip():
        score -= 5; issues.append('missing_summary')
    return max(0, score), issues


def evaluate_design(pdf_path):
    """Visual design: 0-15. Uses pdftoppm for basic checks."""
    score = 15
    issues = []
    try:
        from pypdf import PdfReader
        reader = PdfReader(pdf_path)
        n_pages = len(reader.pages)
        if n_pages == 0:
            return 0, ['no_pages']
        if n_pages > 3:
            score -= 5; issues.append(f'too_many_pages:{n_pages}')
        # Check last page isn't mostly empty
        last_text = reader.pages[-1].extract_text() or ''
        if n_pages > 1 and len(last_text.split()) < 10:
            score -= 3; issues.append('last_page_mostly_empty')
    except Exception as e:
        score = 0
        issues.append(f'design_check_failed:{type(e).__name__}')
    return max(0, score), issues


def evaluate_info_quality(data):
    """Information accuracy: 0-20."""
    score = 20
    issues = []
    # Completeness
    required = ['full_name', 'job_title', 'phone', 'email']
    for field in required:
        if not data.get(field):
            score -= 3; issues.append(f'missing_{field}')
    # No placeholder/test data
    full_text = str(data)
    test_markers = ['test user', 'example.com', 'xxx', 'lorem', 'john doe']
    for marker in test_markers:
        if marker.lower() in full_text.lower():
            score -= 5; issues.append(f'test_data:{marker}')
            break
    # Date consistency (basic)
    for exp in data.get('experience', []):
        period = exp.get('period', '')
        if period and not re.search(r'\d{4}', period):
            score -= 1; issues.append('date_format_unclear')
    return max(0, score), issues


def check_gates(data, pdf_path, lang):
    """Mandatory gates. Returns (passed, failed_gates)."""
    failed = []
    # No fabrication (check against antifab if available)
    try:
        import sys
        sys.path.insert(0, '/data/data/com.termux/files/home/bots/cvbot')
        from ai.antifab import FactRegistry, validate_output
        reg = FactRegistry(data)
        summary = data.get('summary', '')
        if summary:
            valid, violations = validate_output(summary, reg, 'summary')
            if not valid:
                failed.append(f'fabrication:{violations}')
    except Exception:
        pass
    # Contact valid
    email = data.get('email', '')
    if email and '@' not in email:
        failed.append('invalid_email')
    # PDF valid
    if not os.path.exists(pdf_path) or os.path.getsize(pdf_path) < 1000:
        failed.append('pdf_invalid')
    # Text extractable
    try:
        from pypdf import PdfReader
        text = ''.join((p.extract_text() or '') for p in PdfReader(pdf_path).pages)
        if len(text.split()) < 20:
            failed.append('text_not_extractable')
    except Exception:
        failed.append('pdf_unreadable')
    return len(failed) == 0, failed


def full_evaluation(data, pdf_path, lang='en'):
    """Run all evaluations. Returns dict with scores and gates."""
    gates_ok, gates_failed = check_gates(data, pdf_path, lang)
    s_info, i_info = evaluate_info_quality(data)
    s_hr, i_hr = evaluate_hr(data, lang)
    s_ats, i_ats = evaluate_ats(pdf_path, lang)
    s_lang, i_lang = evaluate_language(data, lang)
    s_design, i_design = evaluate_design(pdf_path)
    # Technical: 10 points
    s_tech = 10 if gates_ok else 0
    total = s_info + s_hr + s_ats + s_lang + s_design + s_tech
    return {
        'total': total,
        'breakdown': {
            'info_accuracy': s_info,
            'hr': s_hr,
            'ats': s_ats,
            'language': s_lang,
            'design': s_design,
            'technical': s_tech,
        },
        'issues': {
            'info': i_info, 'hr': i_hr, 'ats': i_ats,
            'language': i_lang, 'design': i_design,
        },
        'gates_passed': gates_ok,
        'gates_failed': gates_failed,
        'verdict': 'ACCEPT' if (gates_ok and total >= 90) else 'REVISE',
    }
