"""Anti-fabrication system: fact registry + mechanical output validation.

This is NOT prompt engineering. It mechanically verifies LLM outputs
against user-provided facts before they reach the CV.
"""
import re


class FactRegistry:
    """All verifiable facts from user input. Nothing else may appear as fact."""

    def __init__(self, data):
        self.companies = set()
        self.periods = set()
        self.titles = set()
        self.schools = set()
        self.skills = set()
        self.numbers = set()  # every number the user provided
        self.target_job = (data.get('target_job') or '').strip()
        self.job_title = (data.get('job_title') or '').strip()
        self.full_name = (data.get('full_name') or '').strip()

        for e in (data.get('experience') or []):
            if e.get('company'):
                self.companies.add(e['company'].strip())
            if e.get('period'):
                self.periods.add(e['period'].strip())
            if e.get('title'):
                self.titles.add(e['title'].strip())
            # Extract numbers from all experience fields
            for v in (e.get('company', ''), e.get('period', ''),
                      e.get('title', ''), e.get('desc', '')):
                self.numbers.update(re.findall(r'\d+', str(v)))

        edu = data.get('education') or ''
        if edu:
            # School names: split on common separators, keep substantial parts
            for part in re.split(r'[-–,،\n]', edu):
                p = part.strip()
                if p and len(p) > 3:
                    self.schools.add(p)
            self.numbers.update(re.findall(r'\d+', edu))

        skills = data.get('skills') or []
        if isinstance(skills, str):
            skills = [s.strip() for s in re.split(r'[,\n]', skills) if s.strip()]
        for s in skills:
            self.skills.add(s.strip())
            self.numbers.update(re.findall(r'\d+', str(s)))

        # Numbers from achievements (user-provided metrics are allowed verbatim)
        ach = data.get('achievements') or ''
        if isinstance(ach, str):
            self.numbers.update(re.findall(r'\d+', ach))

    def allows_number(self, num_str):
        """A number is allowed if user provided it or it's simple arithmetic
        on user periods (e.g. 2024-2021=3 years)."""
        if num_str in self.numbers:
            return True
        # Allow year-difference calculations
        years = [int(n) for n in self.numbers if len(n) == 4 and 1950 < int(n) < 2030]
        if len(years) >= 2:
            diffs = {str(abs(a - b)) for a in years for b in years if a != b}
            if num_str in diffs:
                return True
        return False


# Phrases that assert unverified qualities or intent
BANNED_PATTERNS = [
    # Assumed career intent
    r'أتطلع\s+(الآن\s+)?إلى',
    r'أسعى\s+إلى',
    r'طموحي',
    r'هدفي\s+(المهني|الوظيفي)',
    # Unverifiable superlatives about employers
    r'شركة\s+\S*\s*رائدة',
    r'مؤسسة\s+\S*\s*رائدة',
    r'من\s+كبرى\s+الشركات',
    # Unverifiable quality claims
    r'نتائج\s+إيجابية',
    r'نجاح\s+باهر',
    r'أداء\s+استثنائي',
    r'خبرة\s+واسعة',  # unless years support it - handled separately
    r'معلومات\s+\S*\s*المعقدة',
    r'بثقة\s+(تامة|كبيرة)',
    # Empty marketing
    r'شغوف',
    r'متحمس\s+للعمل',
    r'أسعى\s+للمساهمة\s+بخبرتي\s+في\s+تطوير\s+العمل',  # rule-based filler
]

# Adjectives that upgrade a user fact to an unverified claim
EMBELLISHMENT_ADJECTIVES = [
    'رائدة', 'الرائدة', 'كبرى', 'الكبرى', 'مرموقة', 'المرموقة',
    'المعقدة', 'معقدة', 'المتقدمة', 'متقدمة',
]


def validate_output(text, registry, context='summary'):
    """Mechanically validate LLM output against facts.
    Returns (is_valid, violations_list)."""
    violations = []

    if not text or len(text.strip()) < 20:
        violations.append('too_short')
        return False, violations

    # 1. Check numbers
    for num in re.findall(r'\d+', text):
        # Skip numbers that are part of the user's own phone/email
        if not registry.allows_number(num):
            violations.append(f'unverified_number:{num}')

    # 2. Check banned patterns (unverifiable claims)
    for pat in BANNED_PATTERNS:
        if re.search(pat, text):
            violations.append(f'banned_phrase:{pat[:30]}')

    # 3. Check embellishment: adjective + user entity
    for adj in EMBELLISHMENT_ADJECTIVES:
        # If adjective appears near a company name, it's embellishment
        for comp in registry.companies:
            # Simple proximity check: adj within 5 words of company
            if adj in text and comp[:10] in text:
                # Check they're in the same sentence
                for sent in re.split(r'[.।]', text):
                    if adj in sent and comp[:10] in sent:
                        violations.append(f'embellishment:{adj}')
                        break

    # 4. Summary-specific: shouldn't be too long
    if context == 'summary':
        words = len(text.split())
        if words > 80:
            violations.append(f'too_long:{words}_words')
        # Shouldn't repeat job title more than twice
        jt = registry.job_title
        if jt and text.count(jt) > 2:
            violations.append('title_repetition')

    # 5. Check for placeholder/test data leakage
    if re.search(r'TEST|test\.com|example\.com', text, re.I):
        violations.append('test_data_leak')

    return len(violations) == 0, violations


def sanitize_summary(text, registry):
    """Remove or flag problematic parts. Returns cleaned text."""
    # Remove banned phrases (simple removal)
    for pat in BANNED_PATTERNS:
        text = re.sub(pat, '', text)
    # Clean up double spaces and empty sentences
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'\.\s*\.', '.', text)
    return text
