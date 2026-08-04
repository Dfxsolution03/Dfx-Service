"""
JROS Service Tests — TokenService (Module 18)
================================================

Pure unit tests, no DB — TokenService is just secure-random-token generation
and hashing, shared by password reset and email verification.
"""

from app.services.token_service import TokenService
from app.core.security import hash_token_sha256


class TestGenerateRawToken:
    def test_returns_a_string(self):
        token = TokenService.generate_raw_token()
        assert isinstance(token, str)
        assert len(token) > 30  # 256 bits, url-safe base64 — comfortably long

    def test_two_calls_produce_different_tokens(self):
        assert TokenService.generate_raw_token() != TokenService.generate_raw_token()

    def test_is_url_safe(self):
        token = TokenService.generate_raw_token()
        # url-safe base64 alphabet only: letters, digits, '-', '_'
        assert all(c.isalnum() or c in "-_" for c in token)


class TestHashToken:
    def test_matches_existing_sha256_helper(self):
        raw = "some-raw-token-value"
        assert TokenService.hash_token(raw) == hash_token_sha256(raw)

    def test_is_deterministic(self):
        raw = TokenService.generate_raw_token()
        assert TokenService.hash_token(raw) == TokenService.hash_token(raw)

    def test_different_tokens_hash_differently(self):
        a = TokenService.generate_raw_token()
        b = TokenService.generate_raw_token()
        assert TokenService.hash_token(a) != TokenService.hash_token(b)

    def test_raw_token_never_equals_its_hash(self):
        raw = TokenService.generate_raw_token()
        assert TokenService.hash_token(raw) != raw
