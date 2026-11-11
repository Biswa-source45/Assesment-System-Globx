"""Password hashing (scrypt), JWT (HS256), TOTP and token helpers - stdlib only."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import struct
import time
from typing import Any, Dict, Optional

from app.core.config import get_settings

# ---------------------------------------------------------------- passwords
_SCRYPT = dict(n=2 ** 14, r=8, p=1, dklen=32)


def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(pw.encode(), salt=salt, **_SCRYPT)
    return "scrypt$%s$%s" % (base64.b64encode(salt).decode(), base64.b64encode(dk).decode())


def verify_password(pw: str, stored: Optional[str]) -> bool:
    if not stored or not stored.startswith("scrypt$"):
        return False
    try:
        _, s, h = stored.split("$")
        dk = hashlib.scrypt(pw.encode(), salt=base64.b64decode(s), **_SCRYPT)
        return hmac.compare_digest(dk, base64.b64decode(h))
    except Exception:
        return False


def password_policy_error(pw: str) -> Optional[str]:
    if len(pw) < 8:
        return "Password must be at least 8 characters"
    if not any(c.isdigit() for c in pw) or not any(c.isalpha() for c in pw):
        return "Password must contain letters and digits"
    return None


# ---------------------------------------------------------------- tokens
def sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def new_password(n: int = 8) -> str:
    """Readable generated password (no 0/O/1/l/I); always has a letter and a digit."""
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(n))
        if any(c.isdigit() for c in pw) and any(c.isalpha() for c in pw):
            return pw


def new_otp() -> str:
    return f"{secrets.randbelow(10 ** 6):06d}"


def hash_otp(email: str, code: str) -> str:
    key = get_settings().secret_key.encode()
    return hmac.new(key, f"{email.lower()}:{code}".encode(), hashlib.sha256).hexdigest()


# ---------------------------------------------------------------- JWT (HS256)
def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _b64u_dec(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def jwt_encode(payload: Dict[str, Any], ttl_seconds: int) -> str:
    now = int(time.time())
    body = {**payload, "iat": now, "exp": now + ttl_seconds, "jti": secrets.token_hex(8)}
    h = _b64u(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    p = _b64u(json.dumps(body, separators=(",", ":")).encode())
    sig = hmac.new(get_settings().secret_key.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest()
    return f"{h}.{p}.{_b64u(sig)}"


def jwt_decode(token: str) -> Dict[str, Any]:
    try:
        h, p, s = token.split(".")
    except ValueError as e:
        raise ValueError("malformed token") from e
    exp_sig = hmac.new(get_settings().secret_key.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(exp_sig, _b64u_dec(s)):
        raise ValueError("bad signature")
    body = json.loads(_b64u_dec(p))
    if int(body.get("exp", 0)) < int(time.time()):
        raise ValueError("token expired")
    return body


# ---------------------------------------------------------------- TOTP (RFC 6238)
def new_totp_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode().rstrip("=")


def totp_now(secret: str, t: Optional[float] = None, step: int = 30, digits: int = 6) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    counter = int((t or time.time()) // step)
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[o:o + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return f"{code:0{digits}d}"


def totp_verify(secret: str, code: str, window: int = 1) -> bool:
    now = time.time()
    return any(hmac.compare_digest(totp_now(secret, now + k * 30), (code or "").strip())
               for k in range(-window, window + 1))


def totp_uri(secret: str, email: str, issuer: str = "KAUTILYA") -> str:
    from urllib.parse import quote
    return f"otpauth://totp/{quote(issuer)}:{quote(email)}?secret={secret}&issuer={quote(issuer)}"
