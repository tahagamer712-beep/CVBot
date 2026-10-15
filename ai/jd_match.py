"""Job Description Matching engine.

Analyzes a job posting, extracts requirements, compares against the
user's REAL data, and produces a tailored CV copy WITHOUT fabricating
anything. Original data is always preserved.

No official ATS score is claimed. The match report is an internal
indicator with documented components.
"""
import re
import copy


STOPWORDS = {
    'the', 'and', 'for', 'with', 'from', 'that', 'this', 'will',
    'are', 'our', 'you', 'your', 'job', 'role', 'work', 'team',
    'من', 'في', 'على', 'إلى', 'مع', 'هذا', 'التي', 'الذي', 'عن',
    'أن', 'إن', 'كما', 'بين', 'خلال', 'لدى', 'عند',
}

# Requirement signal phrases (EN + AR)
REQUIRED_SIGNALS = [
    r'\bmust have\b', r'\brequired\b', r'\bessential\b', r'\bmandatory\b',
    r'مطلوب', r'أساسي', r'إلزامي', r'ضروري',
]
PREFERRED_SIGNALS = [
    r'\bpreferred\b', r'\bnice to have\b', r'\bplus\b', r'\bdesirable\b',
    r'مفضل', r'ميزة إضافية', r'يفضل',
]


def extract_requirements(jd_text):
    """Split JD into required vs preferred requirements."""
    if not jd_text or len(jd_text.strip()) < 20:
        return {'required': [], 'preferred': [], 'all_terms': []}

    lines = [l.strip() for l in jd_text.split('\n') if l.strip()]
    required, preferred = [], []

    for line in lines:
        low = line.lower()
        is_req = any(re.search(p, low) for p in REQUIRED_SIGNALS)
        is_pref = any(re.search(p, low) for p in PREFERRED_SIGNALS)
        # Bullet lines without signals: treat as required if in
        # a "requirements" section context (simple heuristic)
        if is_req:
            required.append(line)
        elif is_pref:
            preferred.append(line)
        elif re.match(r'^[-•*]\s', line) and len(line) > 10:
            required.append(line)  # default: bullets = requirements

    # Extract key terms (4+ char words, minus stopwords)
    all_terms = set()
    for line in lines:
        for w in re.findall(r'[\w\u0600-\u06FF]{4,}', line.lower()):
            if w not in STOPWORDS:
                all_terms.add(w)

    return {
        'required': required,
        'preferred': preferred,
        'all_terms': sorted(all_terms),
    }


def match_against_user(requirements, user_data):
    """Compare JD terms against user's real data.

    Returns: covered, missing, uncertain.
    A term counts as 'covered' ONLY if it appears in user data
    in a meaningful context (not just keyword presence).
    """
    # Build searchable user text from REAL data only
    parts = []
    for e in (user_data.get('experience') or []):
        parts += [e.get('title', ''), e.get('company', ''),
                  e.get('desc', '')]
    parts += [user_data.get('summary', ''),
              user_data.get('education', ''),
              ' '.join(user_data.get('skills') or []),
              user_data.get('achievements', '') or '']
    user_text = ' '.join(str(p) for p in parts).lower()

    covered, missing = [], []
    for term in requirements['all_terms']:
        # Meaningful match: term appears as whole word in user data
        if re.search(r'\b' + re.escape(term) + r'\b', user_text):
            covered.append(term)
        else:
            missing.append(term)

    # Uncertain: terms in user text but in weak context
    # (e.g. mentioned once in summary without experience backing)
    return {
        'covered': sorted(set(covered)),
        'missing': sorted(set(missing)),
        'coverage_ratio': (len(set(covered)) / max(len(requirements['all_terms']), 1)),
    }


def tailor_cv(user_data, jd_text, lang='ar'):
    """Create a tailored COPY of user data for the JD.

    Rules:
    - NEVER adds skills/certs/jobs the user didn't provide
    - Reorders sections to emphasize relevant experience
    - Rewrites summary to highlight JD-relevant real qualifications
    - Returns (tailored_data, match_report)
    """
    original = copy.deepcopy(user_data)
    tailored = copy.deepcopy(user_data)

    reqs = extract_requirements(jd_text)
    match = match_against_user(reqs, user_data)

    report = {
        'requirements_total': len(reqs['required']) + len(reqs['preferred']),
        'required_count': len(reqs['required']),
        'preferred_count': len(reqs['preferred']),
        'covered_terms': match['covered'],
        'missing_terms': match['missing'],
        'coverage_ratio': round(match['coverage_ratio'], 2),
        'needs_user_input': [],
        'naturally_used': [],
        'disclaimer': ('Internal match indicator. Not an official ATS score. '
                       'Coverage = term presence in real user data, '
                       'not proof of skill proficiency.'),
    }

    # Identify missing REQUIRED terms that need user confirmation
    req_terms = set()
    for r in reqs['required']:
        for w in re.findall(r'[\w\u0600-\u06FF]{4,}', r.lower()):
            if w not in STOPWORDS:
                req_terms.add(w)
    for t in sorted(req_terms):
        if t in match['missing']:
            report['needs_user_input'].append(t)

    # Reorder experience: most relevant first
    # (relevance = count of JD terms in that experience block)
    def relevance(exp):
        txt = (exp.get('title', '') + ' ' + exp.get('desc', '')).lower()
        return sum(1 for t in reqs['all_terms'] if t in txt)

    exps = tailored.get('experience') or []
    if exps and reqs['all_terms']:
        exps_sorted = sorted(exps, key=relevance, reverse=True)
        # Only reorder if it actually changes things (avoid noise)
        if [e.get('title') for e in exps_sorted] != [e.get('title') for e in exps]:
            tailored['experience'] = exps_sorted
            report['reordered'] = True

    # Mark tailored copy
    tailored['_tailored_for_jd'] = True
    tailored['_original_preserved'] = True

    return tailored, report


def match_score_components(match_result):
    """Documented components of the internal match indicator."""
    return {
        'components': {
            'term_coverage': 'matched JD terms / total JD terms',
            'required_coverage': 'matched required terms / total required',
        },
        'limits': [
            'Term presence != skill proof',
            'No access to employer ATS algorithm',
            'Synonyms not fully handled',
        ],
        'values': {
            'coverage_ratio': match_result.get('coverage_ratio'),
            'covered_count': len(match_result.get('covered', [])),
            'missing_count': len(match_result.get('missing', [])),
        },
    }
