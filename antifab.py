"""Anti-fabrication layer — independent of the writing model.

- Keeps the approved ORIGINAL data snapshot.
- Compares final data vs original; flags deletions/unauthorized changes.
- Names/numbers/dates/certificates: never guessed — flagged for confirmation.
"""
import json
import re


def snapshot_original(data):
    """Serialize the user-approved original data."""
    keep = {k: data.get(k) for k in (
        'full_name', 'phone', 'email', 'address', 'job_title',
        'experience', 'education', 'certs', 'skills', 'languages')}
    return json.dumps(keep, ensure_ascii=False, sort_keys=True)


def _norm(v):
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False, sort_keys=True)
    return str(v or '').strip()


def compare(original_json, final_data):
    """Return list of significant changes: [(field, kind, detail)]."""
    try:
        orig = json.loads(original_json) if original_json else {}
    except Exception:
        return [('__all__', 'unparseable_original', '')]
    changes = []
    for k, ov in orig.items():
        fv = final_data.get(k)
        if _norm(ov) != _norm(fv):
            kind = 'deleted' if not _norm(fv) else 'modified'
            changes.append((k, kind, f'{str(ov)[:60]} -> {str(fv)[:60]}'))
    return changes


SENSITIVE_FIELDS = ('full_name', 'phone', 'email', 'job_title',
                    'education', 'certs')


def sensitive_changed(changes):
    return [c for c in changes if c[0] in SENSITIVE_FIELDS]


def guessy_patterns(text):
    """Detect suspicious invented-looking content (numbers/claims)."""
    if not text:
        return []
    flags = []
    # percentages / money claims the user never wrote are flagged at review
    for m in re.finditer(r'\d+\s*%', text):
        flags.append(('number_claim', m.group(0)))
    return flags
