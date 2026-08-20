"""
JROS Service Tests — Google ID token verification
=================================================

Covers app/services/google_identity_service.py, the single point where a
Google ID token becomes a trusted identity.

Google's own signature check (`google.oauth2.id_token.verify_oauth2_token`) is
patched out — reaching Google to fetch real signing certificates would make
these tests network-dependent and, worse, would require a genuine ID token to
exercise the happy path. What is NOT patched out is everything this module adds
on top of that call, which is where the security-relevant decisions live:

  ✓ Feature disabled when no client ID is configured (fail closed)
  ✓ Audience must be one of OUR client IDs
  ✓ Signature/issuer/expiry rejection is surfaced as 401, without detail
  ✓ Email must be present AND Google-verified
  ✓ Identity is read from token claims, never from anything a client sent
"""

import pytest

from app.core.config import settings
from app.exceptions.base import UnauthorizedException, ValidationException
from app.services import google_identity_service as gis

OUR_CLIENT_ID = "111-ours.apps.googleusercontent.com"
OUR_IOS_CLIENT_ID = "222-ours-ios.apps.googleusercontent.com"

VALID_CLAIMS = {
    "iss": "https://accounts.google.com",
    "aud": OUR_CLIENT_ID,
    "sub": "109876543210987654321",
    "email": "Priya.Sharma@Gmail.com",
    "email_verified": True,
    "name": "Priya Sharma",
    "picture": "https://lh3.googleusercontent.com/a/abc123",
    "exp": 9999999999,
}


@pytest.fixture
def configured(monkeypatch):
    """Two accepted client IDs, mirroring a real Android+iOS deployment."""
    monkeypatch.setattr(
        settings, "GOOGLE_OAUTH_CLIENT_IDS", [OUR_CLIENT_ID, OUR_IOS_CLIENT_ID]
    )


def _patch_google(monkeypatch, claims=None, raises=None):
    """Stand in for Google's verifier. The patched function asserts that this
    module passes `audience=None` — the audience check is deliberately done
    locally against the full allow-list, and a regression that hands a single
    audience to google-auth would silently narrow that."""

    def fake_verify(token, request, audience=None, clock_skew_in_seconds=0):
        assert audience is None, "audience must be checked locally, not by google-auth"
        if raises is not None:
            raise raises
        return dict(claims)

    monkeypatch.setattr(gis.google_id_token, "verify_oauth2_token", fake_verify)


# ═══════════════════════════════════════════════════════════
# 1.  Configuration gate
# ═══════════════════════════════════════════════════════════

class TestConfigurationGate:

    async def test_unconfigured_rejects_even_a_perfect_token(self, monkeypatch):
        """No client ID means no way to validate `aud`, so an unaudienced token
        is not a credential. Must fail closed rather than accept it."""
        monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_IDS", [])
        _patch_google(monkeypatch, claims=VALID_CLAIMS)

        with pytest.raises(ValidationException):
            await gis.verify_google_id_token("any.token.at.all")

    async def test_is_configured_reflects_settings(self, monkeypatch):
        monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_IDS", [])
        assert gis.is_configured() is False
        monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_IDS", [OUR_CLIENT_ID])
        assert gis.is_configured() is True

    async def test_blank_and_whitespace_client_ids_do_not_count(self, monkeypatch):
        """A half-filled env var (GOOGLE_OAUTH_CLIENT_IDS=" , ") must not read
        as configured, or it would enable the feature with no real audience."""
        monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_IDS", ["", "   "])
        assert gis.is_configured() is False

    async def test_comma_separated_string_is_accepted(self, monkeypatch):
        """Settings may arrive pre-split or as a raw string depending on how
        the env var is provided; both must work."""
        monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_IDS", OUR_CLIENT_ID)
        assert gis.is_configured() is True


# ═══════════════════════════════════════════════════════════
# 2.  Audience enforcement
# ═══════════════════════════════════════════════════════════

class TestAudience:

    async def test_token_for_another_app_is_rejected(self, monkeypatch, configured):
        """The core of the confused-deputy defence: a token Google legitimately
        signed for somebody else's OAuth client must not log anyone in here."""
        _patch_google(
            monkeypatch,
            claims={**VALID_CLAIMS, "aud": "999-someone-else.apps.googleusercontent.com"},
        )
        with pytest.raises(UnauthorizedException):
            await gis.verify_google_id_token("token")

    async def test_missing_audience_claim_is_rejected(self, monkeypatch, configured):
        claims = {k: v for k, v in VALID_CLAIMS.items() if k != "aud"}
        _patch_google(monkeypatch, claims=claims)
        with pytest.raises(UnauthorizedException):
            await gis.verify_google_id_token("token")

    async def test_any_configured_client_id_is_accepted(self, monkeypatch, configured):
        """A native iOS build's token carries the iOS client ID — also ours."""
        _patch_google(monkeypatch, claims={**VALID_CLAIMS, "aud": OUR_IOS_CLIENT_ID})
        identity = await gis.verify_google_id_token("token")
        assert identity.subject == VALID_CLAIMS["sub"]


# ═══════════════════════════════════════════════════════════
# 3.  Cryptographic rejection
# ═══════════════════════════════════════════════════════════

class TestSignatureAndExpiry:

    @pytest.mark.parametrize(
        "error",
        [
            ValueError("Token expired"),
            ValueError("Could not verify token signature"),
            ValueError("Wrong issuer"),
        ],
        ids=["expired", "bad-signature", "wrong-issuer"],
    )
    async def test_google_auth_rejection_becomes_401(
        self, monkeypatch, configured, error
    ):
        _patch_google(monkeypatch, raises=error)
        with pytest.raises(UnauthorizedException):
            await gis.verify_google_id_token("token")

    async def test_rejection_reason_is_not_leaked_to_the_caller(
        self, monkeypatch, configured
    ):
        """Whether a token failed on audience, signature or expiry is useful
        only to someone probing the endpoint, so the message stays generic."""
        _patch_google(monkeypatch, raises=ValueError("Token expired, exp=12345"))
        with pytest.raises(UnauthorizedException) as exc:
            await gis.verify_google_id_token("token")
        assert "12345" not in exc.value.message
        assert "expired" not in exc.value.message.lower()

    async def test_empty_token_is_rejected_without_calling_google(
        self, monkeypatch, configured
    ):
        def explode(*a, **kw):
            raise AssertionError("must not attempt to verify an empty token")

        monkeypatch.setattr(gis.google_id_token, "verify_oauth2_token", explode)
        for blank in ("", "   "):
            with pytest.raises(UnauthorizedException):
                await gis.verify_google_id_token(blank)


# ═══════════════════════════════════════════════════════════
# 4.  Email claims
# ═══════════════════════════════════════════════════════════

class TestEmailClaims:

    async def test_unverified_email_is_rejected(self, monkeypatch, configured):
        """An unverified Google address proves nothing about who owns it, and
        this app maps Google accounts onto users *by* email — so accepting one
        would let an attacker claim a victim's address."""
        _patch_google(monkeypatch, claims={**VALID_CLAIMS, "email_verified": False})
        with pytest.raises(UnauthorizedException):
            await gis.verify_google_id_token("token")

    async def test_missing_email_verified_claim_is_rejected(
        self, monkeypatch, configured
    ):
        """Absent must not read as true."""
        claims = {k: v for k, v in VALID_CLAIMS.items() if k != "email_verified"}
        _patch_google(monkeypatch, claims=claims)
        with pytest.raises(UnauthorizedException):
            await gis.verify_google_id_token("token")

    async def test_string_true_is_not_accepted_as_verified(
        self, monkeypatch, configured
    ):
        """`email_verified` must be a real boolean — "false" is truthy."""
        _patch_google(monkeypatch, claims={**VALID_CLAIMS, "email_verified": "false"})
        with pytest.raises(UnauthorizedException):
            await gis.verify_google_id_token("token")

    async def test_missing_email_is_rejected(self, monkeypatch, configured):
        claims = {k: v for k, v in VALID_CLAIMS.items() if k != "email"}
        _patch_google(monkeypatch, claims=claims)
        with pytest.raises(UnauthorizedException):
            await gis.verify_google_id_token("token")

    async def test_missing_subject_is_rejected(self, monkeypatch, configured):
        claims = {k: v for k, v in VALID_CLAIMS.items() if k != "sub"}
        _patch_google(monkeypatch, claims=claims)
        with pytest.raises(UnauthorizedException):
            await gis.verify_google_id_token("token")


# ═══════════════════════════════════════════════════════════
# 5.  Happy path
# ═══════════════════════════════════════════════════════════

class TestVerifiedIdentity:

    async def test_returns_claims_from_the_token(self, monkeypatch, configured):
        _patch_google(monkeypatch, claims=VALID_CLAIMS)
        identity = await gis.verify_google_id_token("  token.with.padding  ")

        assert identity.subject == "109876543210987654321"
        assert identity.name == "Priya Sharma"
        assert identity.picture.startswith("https://")

    async def test_email_is_normalised_to_lowercase(self, monkeypatch, configured):
        """Google preserves the casing the user typed; user lookup compares
        case-insensitively, so the identity is normalised once, here."""
        _patch_google(monkeypatch, claims=VALID_CLAIMS)
        identity = await gis.verify_google_id_token("token")
        assert identity.email == "priya.sharma@gmail.com"

    async def test_absent_optional_claims_become_none(self, monkeypatch, configured):
        """`name`/`picture` are optional — a token without them must still
        verify, since a display name is not an identity."""
        claims = {
            k: v for k, v in VALID_CLAIMS.items() if k not in ("name", "picture")
        }
        _patch_google(monkeypatch, claims=claims)
        identity = await gis.verify_google_id_token("token")
        assert identity.name is None
        assert identity.picture is None
        assert identity.email == "priya.sharma@gmail.com"
