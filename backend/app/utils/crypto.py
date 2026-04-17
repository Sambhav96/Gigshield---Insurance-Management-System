"""utils/crypto.py — SHA-256 hashing for PII (Aadhaar, PAN, bank) and integrity checks."""
import hashlib
import hmac
import base64
from cryptography.fernet import Fernet


def sha256_hash(value: str) -> str:
    """One-way SHA-256 hash. Used for Aadhaar, PAN, bank account IDs."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()


def hmac_sha256(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify_razorpay_webhook(body: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def generate_fernet_key() -> bytes:
    return Fernet.generate_key()


def aes_encrypt(data: str, key: bytes) -> str:
    f = Fernet(key)
    return base64.urlsafe_b64encode(f.encrypt(data.encode())).decode()


def aes_decrypt(token: str, key: bytes) -> str:
    f = Fernet(key)
    return f.decrypt(base64.urlsafe_b64decode(token.encode())).decode()
