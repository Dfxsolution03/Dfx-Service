"""
Google identity verification — the ONLY place a Google ID token is turned into
a trusted identity.

The mobile client sends the raw ID token it received from Google and nothing
else that matters: every identity field used downstream (email, subject, name)
is read out of the *cryptographically verified* token claims here, never out
of the request body. A client can lie about its JSON; it cannot forge Google's
signature.

Verification performed (all of it, in this order):
  1. RS256 signature against Google's published certificates.
  2. `iss` is accounts.google.com / https://accounts.google.com  (google-auth).
  3. `exp` / `iat`, with a small clock-skew allowance                (google-auth).
  4. `aud` is one of OUR registered OAuth client IDs                 (below).
  5. `email` is present and `email_verified` is true                 (below).

Step 4 is done here rather than by passing `audience=` into google-auth
because this app legitimately has more than one client ID (Android/iOS both
request the *web* client ID as their `serverClientId`, but a native iOS
sign-in configured without one mints tokens addressed to the iOS client ID).
google-auth's `verify_oauth2_token` only accepts a single audience, so the
check is done explicitly against the configured allow-list — and it is
mandatory: an empty allow-list rejects everything rather than accepting
anything.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import anyio
from google.auth.transport import requests as google_requests
from google.auth.exceptions import GoogleAuthError
from google.oauth2 import id_token as google_id_token

from app.core.config import settings
from app.core.logging import logger
from app.exceptions.base import UnauthorizedException, ValidationException

# Google's own guidance allows a small amount of clock skew when validating
# `exp`/`iat`. Kept tight — this is a freshly-minted token travelling from a
# handset to this process, not a long-lived credential.
_CLOCK_SKEW_SECONDS = 10

# One transport for the process so the repeated certificate fetches reuse a
# connection pool instead of opening a fresh TLS session per sign-in.
_transport = google_requests.Request()


@dataclass(frozen=True)
class GoogleIdentity:
    """A Google account, as asserted by Google — not by the client."""

    subject: str
    """The `sub` claim: Google's stable, never-reused account identifier. This
    is the real primary key of a Google identity — an account's email address
    can change, `sub` cannot."""

    email: str
    """Lower-cased, Google-verified email address."""

    name: Optional[str]
    picture: Optional[str]


def _allowed_audiences() -> List[str]:
    raw = settings.GOOGLE_OAUTH_CLIENT_IDS
    if isinstance(raw, str):
        raw = [raw]
    return [c.strip() for c in (raw or []) if c and c.strip()]


def is_configured() -> bool:
    """False when no OAuth client ID has been supplied, in which case Google
    sign-in is switched off rather than silently insecure."""
    return bool(_allowed_audiences())


def _verify_blocking(raw_token: str, audiences: List[str]) -> Dict[str, Any]:
    # `audience=None` skips google-auth's own single-audience check; the
    # signature, issuer and expiry checks all still run. The `aud` claim is
    # then matched against the full allow-list below.
    claims = google_id_token.verify_oauth2_token(
        raw_token,
        _transport,
        audience=None,
        clock_skew_in_seconds=_CLOCK_SKEW_SECONDS,
    )

    audience = claims.get("aud")
    if audience not in audiences:
        # Deliberately vague to the caller (see verify_google_id_token) — a
        # token minted for somebody else's OAuth client must not be able to
        # probe which client IDs this backend accepts.
        raise ValueError(f"Token audience '{audience}' is not a registered client ID")

    return claims


async def verify_google_id_token(raw_token: str) -> GoogleIdentity:
    """
    Verify a Google ID token and return the identity Google vouches for.

    Raises ValidationException when the feature isn't configured, and
    UnauthorizedException for every kind of bad token — the caller never gets
    to distinguish "expired" from "wrong audience" from "forged signature",
    since that distinction is only useful to an attacker.
    """
    audiences = _allowed_audiences()
    if not audiences:
        # Fail closed. Without a client ID there is nothing to validate `aud`
        # against, and a token that isn't audience-checked is not a credential.
        raise ValidationException(
            "Google sign-in is not configured on this server.",
            field="id_token",
        )

    if not raw_token or not raw_token.strip():
        raise UnauthorizedException("Google sign-in failed: no ID token was provided")

    try:
        # google-auth is synchronous and fetches Google's signing certificates
        # over the network, so it must not run on the event loop thread.
        claims = await anyio.to_thread.run_sync(
            _verify_blocking, raw_token.strip(), audiences
        )
    except (ValueError, GoogleAuthError) as e:
        # Logged with the reason (useful for diagnosing a client-ID mismatch),
        # returned without it.
        logger.warning(f"Rejected Google ID token: {e}")
        raise UnauthorizedException("Google sign-in failed: the ID token is not valid")

    subject = claims.get("sub")
    email = claims.get("email")
    email_verified = claims.get("email_verified")

    if not subject:
        raise UnauthorizedException("Google sign-in failed: the ID token is not valid")

    # This app identifies users by email address (see AuthService.login_user),
    # so an account whose email Google will not vouch for cannot be mapped
    # onto a user here.
    if not email:
        raise UnauthorizedException(
            "This Google account has no email address, so it cannot be used to sign in."
        )
    if email_verified is not True:
        raise UnauthorizedException(
            "This Google account's email address is not verified. "
            "Verify it with Google, then try again."
        )

    return GoogleIdentity(
        subject=str(subject),
        email=str(email).strip().lower(),
        name=(claims.get("name") or None),
        picture=(claims.get("picture") or None),
    )
