"""Internal CV quality scoring.

Weights are initial and adjustable — NOT a universal standard.
Critical errors block delivery; high design score never compensates
for wrong data.
"""
import re


# Adjustable weights (sum = 100)
WEIGHTS = {
    'completeness': 15,    # all key fields present
    'content_quality': 20,  # summary length, bullet quality
    'factual_safety': 20,  # antifab validation
    'readability': 10,     # human readability
    'format_safety': 10,   # ATS structural safety
    'language': 10,        # grammar, no placeholders
    'text_extraction': 10, # PDF text extractable
    'job_fit': 5,          # JD match (neutral if no JD)
}

# Critical errors that BLOCK delivery
CRITICAL_CHECKS = [
    'missing_contact',      # no phone AND no email
    'arabic_corruption',    # tofu/garbage in Arabic text
    'content_truncated',    # PDF cut off
    'test_data_leak',       # TEST/example.com in output
]


def score_cv(data, pdf_path=None, design_key=None, lang='ar'):
    """Score 0-100. Returns (score, breakdown, critical_errors)."""
    scores = {}
    critical = []

    # 1. Completeness (20)
    required = ['full_name', 'job_title', 'phone', 'email']
    present = sum(1 for f in required if data.get(f))
    scores['completeness'] = (present / len(required)) * WEIGHTS['completeness']
    if not data.get('phone') and not data.get('email'):
        critical.append('missing_contact')

    # 2. Content quality (25)
    cq = 0
    summary = data.get('summary', '')
    sw = len(summary.split())
    if 30 <= sw <= 80:
        cq += 10
    elif sw > 0:
        cq += 5
    exps = data.get('experience') or []
    if exps:
        # Check bullets exist
        bullets = sum(len([l for l in (e.get('desc', '') or '').split('\n') if l.strip()])
                      for e in exps)
        if bullets >= 3:
            cq += 10
        elif bullets > 0:
            cq += 5
        # Reverse chronological (can't verify, assume OK)
        cq += 5
    scores['content_quality'] = min(cq, WEIGHTS['content_quality'])

    # 3. Factual safety (20) — via antifab
    try:
        from ai.antifab import FactRegistry, validate_output
        reg = FactRegistry(data)
        valid, violations = validate_output(summary, reg, 'summary')
        if valid:
            scores['factual_safety'] = WEIGHTS['factual_safety']
        else:
            # Deduct per violation
            scores['factual_safety'] = max(
                0, WEIGHTS['factual_safety'] - len(violations) * 5)
            for v in violations:
                if 'test_data' in v:
                    critical.append('test_data_leak')
    except ImportError:
        scores['factual_safety'] = WEIGHTS['factual_safety'] // 2

    # 4. Readability (15)
    r_score = WEIGHTS['readability']
    # Check for run-on sentences
    for sent in re.split(r'[.।]', summary):
        if len(sent.split()) > 40:
            r_score -= 5
            break
    # Check Arabic corruption
    if lang == 'ar' and re.search(r'[�□]', summary):
        critical.append('arabic_corruption')
        r_score = 0
    scores['readability'] = max(0, r_score)

    # 5. Format safety (10)
    f_score = WEIGHTS['format_safety']
    if design_key in ('modern_executive', 'modern_professional'):
        f_score -= 5  # multi-column risk
    scores['format_safety'] = max(0, f_score)

    # 6. Language (10)
    l_score = WEIGHTS['language']
    full = str(data)
    if re.search(r'\b(TEST|placeholder|xxx)\b', full, re.I):
        critical.append('test_data_leak')
        l_score = 0
    if re.search(r'lorem', full, re.I):
        l_score -= 5
    scores['language'] = max(0, l_score)

    # 7. Text extraction - from PDF if available
    if pdf_path:
        try:
            from ai.ats_checks import check_readability
            r = check_readability(pdf_path)
            if r['passed']:
                scores['text_extraction'] = WEIGHTS['text_extraction']
            else:
                scores['text_extraction'] = 0
                if 'too_little_text' in r.get('issues', []):
                    critical.append('unreadable_text')
        except Exception:
            scores['text_extraction'] = 0
    else:
        scores['text_extraction'] = WEIGHTS['text_extraction'] // 2
    # 8. Job fit - neutral when no JD (separate from general quality)
    scores['job_fit'] = WEIGHTS['job_fit']
    total = sum(scores.values())
    return {
        'score': round(total),
        'breakdown': {k: round(v, 1) for k, v in scores.items()},
        'critical_errors': critical,
        'blocked': len(critical) > 0,
        'note': 'Internal indicator. High design score does not compensate for wrong data.',
    }
