"""Smart receipt verification for manual Keycard payments.

Architecture:
- Image validation (Pillow): real type, dimensions, not corrupt
- Perceptual hash (dHash): duplicate detection across crops/resizes
- OCR (pytesseract): best-effort; graceful degradation to manual review
- Business rules: amount match, completion signals, review-screen detection
- DB-level duplicate tracking via transaction refs + image hashes

CRITICAL: OCR absence or failure NEVER auto-approves. It routes to admin.
Reading a receipt image never proves money arrival without official
verification from the payment provider.
"""
import os
import re
import hashlib
import sqlite3

# --- Image validation ---
def validate_image(path):
    """Check real file type, readability, dimensions."""
    result = {'valid': False, 'reason': '', 'width': 0, 'height': 0,
              'format': '', 'size_bytes': 0}
    try:
        size = os.path.getsize(path)
        result['size_bytes'] = size
        if size < 1024:
            result['reason'] = 'file_too_small'
            return result
        if size > 20 * 1024 * 1024:
            result['reason'] = 'file_too_large'
            return result
        from PIL import Image
        with Image.open(path) as img:
            img.verify()  # check integrity without full decode
        with Image.open(path) as img:
            result['format'] = img.format or ''
            result['width'], result['height'] = img.size
        if result['format'] not in ('JPEG', 'PNG', 'WEBP'):
            result['reason'] = f"unsupported_format:{result['format']}"
            return result
        if result['width'] < 200 or result['height'] < 200:
            result['reason'] = 'image_too_small'
            return result
        result['valid'] = True
        return result
    except Exception as e:
        result['reason'] = f'unreadable:{type(e).__name__}'
        return result


def perceptual_hash(path, hash_size=8):
    """dHash: robust to resize/compress/crop variations."""
    try:
        from PIL import Image
        with Image.open(path).convert('L') as img:
            img = img.resize((hash_size + 1, hash_size), Image.LANCZOS)
            pixels = list(img.getdata())
            bits = []
            for row in range(hash_size):
                for col in range(hash_size):
                    left = pixels[row * (hash_size + 1) + col]
                    right = pixels[row * (hash_size + 1) + col + 1]
                    bits.append('1' if left > right else '0')
            return hex(int(''.join(bits), 2))[2:].zfill(hash_size * hash_size // 4)
    except Exception:
        return None


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def hamming_distance(h1, h2):
    """Bit difference between two hex hashes."""
    if not h1 or not h2 or len(h1) != len(h2):
        return None
    b1 = bin(int(h1, 16))[2:].zfill(len(h1) * 4)
    b2 = bin(int(h2, 16))[2:].zfill(len(h2) * 4)
    return sum(c1 != c2 for c1, c2 in zip(b1, b2))


# --- OCR (best-effort) ---
def extract_text_ocr(path):
    """Returns (text, ocr_available). Never raises."""
    try:
        import pytesseract
        from PIL import Image
        # Check binary exists
        import shutil
        if not shutil.which('tesseract'):
            return '', False
        with Image.open(path) as img:
            # Try Arabic + English
            try:
                text = pytesseract.image_to_string(img, lang='ara+eng')
            except Exception:
                text = pytesseract.image_to_string(img)
            return text or '', True
    except Exception:
        return '', False


# --- Field extraction from OCR text ---
COMPLETION_SIGNALS = [
    r'تم\s*إرسال\s*المبلغ',
    r'تم\s*التحويل',
    r'عملية\s*ناجحة',
    r'تم\s*الدفع',
    r'successful', r'completed',
    r'transfer\s*completed',  # OCR-tolerant
    r'sttus\s*successful',     # OCR error variant
]
REVIEW_SIGNALS = [
    r'مراجعة\s*وإرسال',
    r'مراجعة\s*التحويل',
    r'review\s*and\s*send',
    r'تأكيد\s*التحويل',
]
AMOUNT_PATTERNS = [
    r'(\d[\d,]*)\s*د\.?ع',
    r'(\d[\d,]*)\s*IQD',
    r'(\d[\d,]*)\s*[I1][QO0][D0]',  # OCR-tolerant: 10D, IQD, 1QD
    r'المبلغ[:\s]*(\d[\d,]*)',
    r'Amount[:\s]*(\d[\d,]*)',
]
TXN_REF_PATTERNS = [
    r'رقم\s*الحركة[:\s]*(\d{10,})',
    r'رقم\s*العملية[:\s]*(\d{10,})',
    r'transaction[:\s]*(\d{10,})',
    r'reference[:\s]*(\d{10,})',
]

def analyze_receipt_text(text):
    """Extract fields and classify receipt type from OCR text."""
    result = {
        'completion_signals': [],
        'review_signals': [],
        'amounts': [],
        'txn_refs': [],
        'classification': 'unknown',
    }
    if not text:
        return result
    for pat in COMPLETION_SIGNALS:
        if re.search(pat, text, re.I):
            result['completion_signals'].append(pat[:20])
    for pat in REVIEW_SIGNALS:
        if re.search(pat, text, re.I):
            result['review_signals'].append(pat[:20])
    for pat in AMOUNT_PATTERNS:
        for m in re.findall(pat, text):
            try:
                result['amounts'].append(int(m.replace(',', '')))
            except ValueError:
                pass
    for pat in TXN_REF_PATTERNS:
        result['txn_refs'].extend(re.findall(pat, text, re.I))
    # Classify
    if result['review_signals'] and not result['completion_signals']:
        result['classification'] = 'review_screen'
    elif result['completion_signals']:
        result['classification'] = 'completed_transfer'
    elif result['amounts']:
        result['classification'] = 'has_amount_no_status'
    return result


# --- Main verification ---
def verify_receipt(image_path, expected_amount, order_id=None, db_path=None):
    """Full verification pipeline.

    Returns dict with:
    - decision: 'approved' | 'rejected' | 'manual_review'
    - reason: machine-readable code
    - fields: extracted data (amounts, refs, hashes)
    - confidence: low|medium|high

    NEVER auto-approves on OCR failure or missing evidence.
    Final approval always requires admin for manual Keycard payments.
    """
    out = {
        'decision': 'manual_review',
        'reason': 'default_manual',
        'fields': {},
        'confidence': 'low',
        'ocr_available': False,
    }

    # 1. Image validation
    iv = validate_image(image_path)
    out['fields']['image'] = iv
    if not iv['valid']:
        out['decision'] = 'rejected'
        out['reason'] = f"invalid_image:{iv['reason']}"
        return out

    # 2. Hashes for duplicate detection
    sha = file_sha256(image_path)
    phash = perceptual_hash(image_path)
    out['fields']['sha256'] = sha[:16] + '...'  # truncated in output
    out['fields']['phash'] = phash
    out['fields']['_sha_full'] = sha  # internal use

    # 3. Check DB for reuse
    if db_path and order_id:
        dup = check_duplicate(db_path, sha, phash, order_id)
        if dup['is_duplicate']:
            out['decision'] = 'manual_review'
            out['reason'] = f"suspected_reuse:{dup['matched_order']}"
            out['fields']['duplicate'] = dup
            out['confidence'] = 'medium'
            return out

    # 4. OCR
    text, ocr_ok = extract_text_ocr(image_path)
    out['ocr_available'] = ocr_ok
    out['fields']['ocr_text_length'] = len(text)
    if not ocr_ok:
        out['decision'] = 'manual_review'
        out['reason'] = 'ocr_unavailable'
        out['confidence'] = 'low'
        return out
    if not text.strip():
        out['decision'] = 'manual_review'
        out['reason'] = 'ocr_empty'
        return out

    # 5. Analyze
    analysis = analyze_receipt_text(text)
    out['fields']['analysis'] = {
        'classification': analysis['classification'],
        'amounts': analysis['amounts'],
        'txn_refs': [r[:6] + '...' for r in analysis['txn_refs']],
        'completion': len(analysis['completion_signals']) > 0,
        'review_screen': len(analysis['review_signals']) > 0,
    }
    out['fields']['_txn_refs_full'] = analysis['txn_refs']

    # 6. Decision rules
    cls = analysis['classification']
    if cls == 'review_screen':
        # Reference image #2 case: NOT proof of completed transfer
        out['decision'] = 'manual_review'
        out['reason'] = 'review_screen_not_proof'
        out['confidence'] = 'high'
        return out

    if analysis['amounts']:
        matched = expected_amount in analysis['amounts']
        out['fields']['amount_match'] = matched
        out['fields']['expected'] = expected_amount
        if not matched:
            out['decision'] = 'manual_review'
            out['reason'] = (f"amount_mismatch:expected_{expected_amount}_"
                             f"found_{analysis['amounts']}")
            out['confidence'] = 'high'
            return out

    if cls == 'completed_transfer' and analysis['amounts']:
        # Strong signals but STILL requires admin for Keycard
        # (no official verification API)
        out['decision'] = 'manual_review'
        out['reason'] = 'strong_signals_needs_admin'
        out['confidence'] = 'high'
        return out

    # Default: manual review
    out['decision'] = 'manual_review'
    out['reason'] = f'insufficient_evidence:{cls}'
    return out


def check_duplicate(db_path, sha256_full, phash, current_order_id,
                    phash_threshold=5):
    """Check if receipt was used before. Returns match info."""
    result = {'is_duplicate': False, 'matched_order': None,
              'match_type': None}
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        # Exact SHA match
        row = conn.execute(
            "SELECT order_id FROM receipt_hashes WHERE sha256=? AND order_id!=?",
            (sha256_full, current_order_id)).fetchone()
        if row:
            result.update(is_duplicate=True, matched_order=row['order_id'],
                          match_type='exact')
            conn.close()
            return result
        # Perceptual near-match
        if phash:
            for r in conn.execute(
                    "SELECT order_id, phash FROM receipt_hashes WHERE order_id!=?",
                    (current_order_id,)):
                if r['phash']:
                    dist = hamming_distance(phash, r['phash'])
                    if dist is not None and dist <= phash_threshold:
                        result.update(is_duplicate=True,
                                      matched_order=r['order_id'],
                                      match_type=f'perceptual_d{dist}')
                        break
        conn.close()
    except Exception:
        pass
    return result


def record_receipt(db_path, order_id, sha256_full, phash, txn_refs):
    """Store receipt fingerprints after admin decision."""
    try:
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS receipt_hashes ("
            "order_id TEXT PRIMARY KEY, sha256 TEXT, phash TEXT, "
            "txn_ref TEXT, recorded_at TEXT)")
        conn.execute(
            "INSERT OR REPLACE INTO receipt_hashes "
            "(order_id, sha256, phash, txn_ref, recorded_at) "
            "VALUES (?,?,?,?,datetime('now'))",
            (order_id, sha256_full, phash,
             ','.join(txn_refs[:3]) if txn_refs else ''))
        # Also check txn_ref reuse across orders
        for ref in txn_refs[:3]:
            row = conn.execute(
                "SELECT order_id FROM receipt_hashes WHERE txn_ref LIKE ? "
                "AND order_id!=?", (f'%{ref}%', order_id)).fetchone()
            if row:
                conn.close()
                return {'txn_reused': True, 'by_order': row['order_id']}
        conn.commit()
        conn.close()
    except Exception:
        pass
    return {'txn_reused': False}
