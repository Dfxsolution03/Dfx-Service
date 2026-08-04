import secrets

from app.core.security import hash_token_sha256

# Excludes visually-ambiguous characters (0/O, 1/l/I) — this password is
# meant to be read off a screen and typed once (or copy-pasted), not
# memorized, so avoiding transcription errors matters more than raw charset
# size for a value this long.
_TEMP_PASSWORD_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%"


class TokenService:
    """
    Generates and hashes single-use security tokens (password reset, email
    verification). This is the one place that logic lives — both features
    call it rather than each rolling their own random-token generation, so
    the security-sensitive part (entropy source, hashing) is written once.

    The actual storage (expiry, one-time-use enforcement via `used_at`) is
    intentionally kept in each feature's own table/service — see
    PasswordResetToken/EmailVerificationToken in app/models/auth.py — since
    those two concerns have no shared query patterns worth abstracting, only
    this token-math step does.
    """

    @staticmethod
    def generate_raw_token() -> str:
        """256 bits of entropy, URL-safe — short enough to put in a query
        string, long enough that brute-forcing it is infeasible."""
        return secrets.token_urlsafe(32)

    @staticmethod
    def hash_token(raw_token: str) -> str:
        """SHA256 hash for at-rest storage — the raw token is never persisted,
        only ever exists in the outbound email link. Reuses the exact same
        helper RefreshToken's hashing already relies on."""
        return hash_token_sha256(raw_token)

    @staticmethod
    def generate_temporary_password(length: int = 14) -> str:
        """Module 29 — a cryptographically random one-time password for a
        freshly-provisioned tenant Admin. Uses `secrets.choice`, the same
        entropy source as `generate_raw_token`, just shaped as a typeable
        password (bcrypt-safe: `hash_password` rejects anything over 72
        bytes, and this alphabet is single-byte ASCII, so length=14 is well
        within range). Never persisted in plaintext anywhere — only its
        bcrypt hash (via `hash_password`) is stored, exactly like every other
        User.hashed_password in this codebase; the raw value is returned to
        the caller exactly once."""
        return "".join(secrets.choice(_TEMP_PASSWORD_ALPHABET) for _ in range(length))
