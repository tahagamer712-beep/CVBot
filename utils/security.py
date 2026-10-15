"""Security helpers — XOR+Base64 obfuscation for API keys (same pattern as wallet bot).

NOT strong encryption: prevents plaintext keys in casual DB views. Real
protection relies on .env secrecy + file permissions (600) on the phone.
"""
import base64
import hashlib
import os

SECRET_KEY = os.environ.get('SECRET_KEY', '')


def _keystream(length: int) -> bytes:
    if not SECRET_KEY:
        raise RuntimeError('SECRET_KEY missing from .env')
    seed = SECRET_KEY.encode('utf-8')
    out = bytearray()
    counter = 0
    while len(out) < length:
        out += hashlib.sha256(seed + counter.to_bytes(4, 'big')).digest()
        counter += 1
    return bytes(out[:length])


def _xor(data: bytes) -> bytes:
    stream = _keystream(len(data))
    return bytes(a ^ b for a, b in zip(data, stream))


def encrypt_key(raw_key: str) -> str:
    return base64.urlsafe_b64encode(_xor(raw_key.encode('utf-8'))).decode('ascii')


def decrypt_key(stored_value: str) -> str:
    return _xor(base64.urlsafe_b64decode(stored_value.encode('ascii'))).decode('utf-8')


def mask_key(raw_key: str) -> str:
    suffix = raw_key[-4:] if len(raw_key) >= 4 else raw_key
    return '\u2022' * 8 + suffix


def is_admin(telegram_id: int, admin_id: int) -> bool:
    return admin_id != 0 and telegram_id == admin_id
