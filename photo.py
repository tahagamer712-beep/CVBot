"""Photo processing: smart 1:1 crop with face preservation.
No face detection library guaranteed — uses center-weighted crop with
optional OpenCV face detection when available. Never invents/changes faces.
"""
import logging
import os

log = logging.getLogger('cvbot')


def detect_face_box(img):
    """Return (x, y, w, h) of primary face or None.
    Tries OpenCV Haar cascade if available; else None (no guessing)."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None
    try:
        gray = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
        cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        if not os.path.exists(cascade_path):
            return None
        fc = cv2.CascadeClassifier(cascade_path)
        faces = fc.detectMultiScale(gray, 1.1, 4)
        if len(faces) == 0:
            return None
        if len(faces) > 1:
            return 'multiple'
        x, y, w, h = faces[0]
        return (int(x), int(y), int(w), int(h))
    except Exception as e:
        log.warning('face detect failed: %s', e)
        return None


def crop_square(src_path, dst_path, size=600):
    """Crop to 1:1 square centered on face (if detected) else image center.
    Returns dict with status info for user messaging."""
    from PIL import Image
    try:
        img = Image.open(src_path)
        img = img.convert('RGB')
    except Exception:
        return {'ok': False, 'reason': 'bad_image'}
    w, h = img.size
    face = detect_face_box(img)

    if face == 'multiple':
        return {'ok': False, 'reason': 'multiple_faces'}
    if face:
        fx, fy, fw, fh = face
        cx, cy = fx + fw // 2, fy + fh // 2
        # square side: cover face with margin, keep head+chin inside
        side = int(max(fw, fh) * 2.2)
        side = min(side, min(w, h))
        # center on face, clamp to image bounds
        x0 = max(0, min(cx - side // 2, w - side))
        y0 = max(0, min(cy - side // 2, h - side))
    else:
        # center crop, no face info — do NOT guess, use center
        side = min(w, h)
        x0 = (w - side) // 2
        y0 = (h - side) // 2

    cropped = img.crop((x0, y0, x0 + side, y0 + side))
    cropped = cropped.resize((size, size), Image.LANCZOS)
    cropped.save(dst_path, 'JPEG', quality=88)
    return {'ok': True, 'face_found': bool(face),
            'reason': 'ok' if face else 'no_face_center_crop'}
