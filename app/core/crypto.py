"""
Symmetric encryption for SuperAdmin-entered integration credentials.

Fernet (AES-128-CBC + HMAC) keyed from INTEGRATION_ENCRYPTION_KEY, an env
var never committed to the repo. If unset, encrypt/decrypt raise instead of
ever falling back to storing plaintext — callers must treat that as a
configuration error, not silently degrade.
"""
import json
from typing import Any, Dict, Optional

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class EncryptionNotConfiguredError(Exception):
    pass


def _get_fernet() -> Fernet:
    if not settings.INTEGRATION_ENCRYPTION_KEY:
        raise EncryptionNotConfiguredError(
            "INTEGRATION_ENCRYPTION_KEY is not set — cannot store integration credentials securely."
        )
    try:
        return Fernet(settings.INTEGRATION_ENCRYPTION_KEY.encode())
    except Exception as exc:
        raise EncryptionNotConfiguredError(f"INTEGRATION_ENCRYPTION_KEY is invalid: {exc}")


def encrypt_json(data: Dict[str, Any]) -> str:
    fernet = _get_fernet()
    return fernet.encrypt(json.dumps(data).encode()).decode()


def decrypt_json(token: str) -> Optional[Dict[str, Any]]:
    fernet = _get_fernet()
    try:
        return json.loads(fernet.decrypt(token.encode()).decode())
    except InvalidToken:
        return None
