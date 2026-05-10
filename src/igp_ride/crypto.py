from __future__ import annotations

import base64
import getpass
import hashlib
import platform

from cryptography.fernet import Fernet, InvalidToken

_SALT = b"igp-ride-credential-encryption-salt-v1"
_ITERATIONS = 100_000
_fernet_cache: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet_cache
    if _fernet_cache is not None:
        return _fernet_cache
    identity = f"{platform.node()}:{_get_user()}"
    key_material = hashlib.pbkdf2_hmac(
        "sha256",
        identity.encode("utf-8"),
        _SALT,
        _ITERATIONS,
    )
    key = base64.urlsafe_b64encode(key_material)
    _fernet_cache = Fernet(key)
    return _fernet_cache


def _get_user() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return "unknown"


def encrypt_value(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_value(token: str) -> str | None:
    try:
        return _get_fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except (InvalidToken, Exception):
        return None
