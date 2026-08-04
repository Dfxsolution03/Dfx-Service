import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
import bcrypt
import jwt
from app.core.config import settings


def hash_password(password: str) -> str:
    """
    Hash password using bcrypt.
    Enforces 72-byte password length limit to prevent bcrypt CPU DoS attacks.
    """
    pwd_bytes = password.encode("utf-8")
    if len(pwd_bytes) > 72:
        raise ValueError("Password cannot exceed 72 bytes")
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(pwd_bytes, salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify plain password against hashed password with length check."""
    try:
        plain_bytes = plain_password.encode("utf-8")
        if len(plain_bytes) > 72:
            return False
        hashed_bytes = hashed_password.encode("utf-8")
        return bcrypt.checkpw(plain_bytes, hashed_bytes)
    except Exception:
        return False


def create_access_token(
    subject: str,
    tenant_id: Optional[str],
    role: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Generate JWT Access Token (short-lived)."""
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    payload: Dict[str, Any] = {
        "sub": subject,
        "tenant_id": tenant_id,
        "role": role,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    encoded_jwt = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def create_refresh_token(
    subject: str,
    tenant_id: Optional[str],
    token_id: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Generate JWT Refresh Token (long-lived)."""
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    payload: Dict[str, Any] = {
        "sub": subject,
        "tenant_id": tenant_id,
        "jti": token_id,
        "type": "refresh",
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    encoded_jwt = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def decode_jwt_token(token: str) -> Dict[str, Any]:
    """
    Decode and validate JWT token claims with strict algorithm pinning.
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={
                "verify_signature": True,
                "verify_exp": True,
                "verify_iat": True,
                "require": ["sub", "type", "exp", "iat"],
            },
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise ValueError("Token has expired")
    except jwt.PyJWTError:
        raise ValueError("Invalid token")


def hash_token_sha256(token: str) -> str:
    """Hash refresh token string using SHA256 for secure database storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
