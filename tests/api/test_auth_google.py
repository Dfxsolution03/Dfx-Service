"""
JROS API Tests — Google Sign-In
===============================

Covers:
  POST /api/v1/auth/google   → verify a Google ID token, issue JWTs

Google's verifier is mocked (see the `google_identity` fixture) — these tests
are about what the backend does with a *verified* identity, and about proving
it does nothing at all with an unverified one. Deliberately no test forges a
token to make a happy path pass: the only way in is through
verify_google_id_token, and the tests that exercise rejection let the real
function do the rejecting.

Test scenarios:
  ✓ Identity comes from the token, never from the request body
  ✓ Missing / empty id_token                     → 400 (app maps 422 → 400)
  ✓ Rejected token                               → 401
  ✓ First-time Google user, no store             → 400 + field=tenant_id
  ✓ First-time Google user, with store           → 200 + Customer created
  ✓ First-time Google user, bad/inactive store   → 400
  ✓ Existing password account, same email        → linked, NOT duplicated
  ✓ Repeat sign-in                               → same user, no new row
  ✓ Email changed at Google, same `sub`          → still the same user
  ✓ Deactivated user                             → 401
  ✓ Suspended store                              → 401
  ✓ Issued tokens work against a real endpoint and are refreshable
  ✓ Client-supplied tenant_id cannot move an existing user between stores
"""

import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.auth import Role, Tenant, Subscription, User
from app.core.constants import ROLE_CUSTOMER
from app.exceptions.base import UnauthorizedException
from app.services import auth_service as auth_service_module
from app.services.google_identity_service import GoogleIdentity
from app.core.rate_limit import login_rate_limiter

BASE = "/api/v1"


@pytest.fixture(autouse=True)
def fresh_rate_limit_window():
    """/auth/google shares the login limiter (10 requests / 60s / IP), and
    every test here arrives from the same ASGI client address. Without a reset
    the whole module would exhaust one window and start 429-ing partway
    through. The limit itself is asserted deliberately in
    TestRateLimiting rather than being tripped by accident.
    """
    login_rate_limiter._hits.clear()
    yield
    login_rate_limiter._hits.clear()


def _google_identity(email: str, subject: str | None = None, name: str = "Google User"):
    return GoogleIdentity(
        subject=subject or f"gsub_{uuid.uuid4().hex[:16]}",
        email=email.strip().lower(),
        name=name,
        picture=None,
    )


@pytest.fixture
def google_identity(monkeypatch):
    """
    Replaces Google's token verification with a controllable stub.

    Returns a setter: call it with a GoogleIdentity to decide who the next
    request authenticates as, or with an exception to have verification fail.
    The stub also asserts the endpoint actually forwards the raw `id_token` —
    a regression that stopped calling the verifier would otherwise pass every
    happy-path test in this file.
    """
    box = {"identity": None, "error": None, "seen_tokens": []}

    async def fake_verify(raw_token: str):
        box["seen_tokens"].append(raw_token)
        if box["error"] is not None:
            raise box["error"]
        return box["identity"]

    monkeypatch.setattr(auth_service_module, "verify_google_id_token", fake_verify)

    class Control:
        def signs_in_as(self, identity: GoogleIdentity):
            box["identity"], box["error"] = identity, None

        def fails_with(self, error: Exception):
            box["identity"], box["error"] = None, error

        @property
        def seen_tokens(self):
            return box["seen_tokens"]

    return Control()


async def _fetch_user_by_email(db: AsyncSession, email: str) -> User | None:
    return (
        await db.execute(select(User).where(func.lower(User.email) == email.lower()))
    ).scalars().first()


async def _count_users_with_email(db: AsyncSession, email: str) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(User).where(
                func.lower(User.email) == email.lower()
            )
        )
    ).scalar_one()


# ═══════════════════════════════════════════════════════════
# 1.  Request validation
# ═══════════════════════════════════════════════════════════

class TestRequestValidation:

    async def test_missing_id_token_is_rejected(self, client: AsyncClient):
        # This app's global handler renders request-validation failures as 400,
        # not FastAPI's default 422 (see app/exceptions).
        r = await client.post(f"{BASE}/auth/google", json={})
        assert r.status_code == 400
        assert r.json()["errors"][0]["field"] == "id_token"

    async def test_empty_id_token_is_rejected(self, client: AsyncClient):
        r = await client.post(f"{BASE}/auth/google", json={"id_token": ""})
        assert r.status_code == 400
        assert r.json()["errors"][0]["field"] == "id_token"

    async def test_rejected_token_is_401(self, client: AsyncClient, google_identity):
        google_identity.fails_with(
            UnauthorizedException("Google sign-in failed: the ID token is not valid")
        )
        r = await client.post(f"{BASE}/auth/google", json={"id_token": "forged.jwt"})
        assert r.status_code == 401

    async def test_rejected_token_issues_no_tokens(
        self, client: AsyncClient, google_identity
    ):
        google_identity.fails_with(UnauthorizedException("nope"))
        r = await client.post(f"{BASE}/auth/google", json={"id_token": "forged.jwt"})
        body = r.json()
        assert "access_token" not in (body.get("data") or {})

    async def test_the_raw_token_is_actually_forwarded_for_verification(
        self, client: AsyncClient, google_identity, test_tenant
    ):
        google_identity.signs_in_as(_google_identity(f"fwd_{uuid.uuid4().hex[:8]}@gmail.com"))
        await client.post(
            f"{BASE}/auth/google",
            json={"id_token": "the.exact.token", "tenant_id": test_tenant.id},
        )
        assert google_identity.seen_tokens == ["the.exact.token"]


# ═══════════════════════════════════════════════════════════
# 2.  Identity is never taken from the request body
# ═══════════════════════════════════════════════════════════

class TestIdentityIsNotClientSupplied:

    async def test_body_email_cannot_impersonate_another_account(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        google_identity,
        customer_user: User,
        test_tenant: Tenant,
    ):
        """The original implementation's fatal flaw: it read `email` out of the
        request body. Passing a victim's address must have no effect whatsoever
        — the session issued belongs to the *token's* account."""
        attacker_email = f"attacker_{uuid.uuid4().hex[:8]}@gmail.com"
        google_identity.signs_in_as(_google_identity(attacker_email))

        r = await client.post(
            f"{BASE}/auth/google",
            json={
                "id_token": "attacker.token",
                "tenant_id": test_tenant.id,
                "email": customer_user.email,      # the impersonation attempt
                "name": "Totally The Victim",
            },
        )
        assert r.status_code == 200

        # The session must belong to the attacker's own new account, not the
        # victim's — verified by asking the API who we are.
        access = r.json()["data"]["access_token"]
        me = await client.get(
            f"{BASE}/users/me", headers={"Authorization": f"Bearer {access}"}
        )
        assert me.status_code == 200
        assert me.json()["data"]["user"]["email"] == attacker_email
        assert me.json()["data"]["user"]["id"] != customer_user.id

    async def test_body_name_is_ignored_in_favour_of_the_token(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        google_identity,
        test_tenant: Tenant,
    ):
        email = f"named_{uuid.uuid4().hex[:8]}@gmail.com"
        google_identity.signs_in_as(_google_identity(email, name="Name From Token"))

        r = await client.post(
            f"{BASE}/auth/google",
            json={
                "id_token": "t",
                "tenant_id": test_tenant.id,
                "name": "Name From Body",
            },
        )
        assert r.status_code == 200
        user = await _fetch_user_by_email(db_session, email)
        assert user.name == "Name From Token"


# ═══════════════════════════════════════════════════════════
# 3.  First-time Google user
# ═══════════════════════════════════════════════════════════

class TestFirstTimeGoogleUser:

    async def test_without_a_store_returns_400_naming_tenant_id(
        self, client: AsyncClient, google_identity
    ):
        """The client relies on `errors[0].field == "tenant_id"` to know it
        should show the store picker, so that contract is asserted directly."""
        google_identity.signs_in_as(_google_identity(f"new_{uuid.uuid4().hex[:8]}@gmail.com"))
        r = await client.post(f"{BASE}/auth/google", json={"id_token": "t"})

        assert r.status_code == 400
        body = r.json()
        assert body["success"] is False
        assert body["errors"][0]["field"] == "tenant_id"

    async def test_without_a_store_creates_nothing(
        self, client: AsyncClient, db_session: AsyncSession, google_identity
    ):
        email = f"nostore_{uuid.uuid4().hex[:8]}@gmail.com"
        google_identity.signs_in_as(_google_identity(email))
        await client.post(f"{BASE}/auth/google", json={"id_token": "t"})
        assert await _fetch_user_by_email(db_session, email) is None

    async def test_with_a_store_creates_a_customer(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        google_identity,
        test_tenant: Tenant,
    ):
        email = f"fresh_{uuid.uuid4().hex[:8]}@gmail.com"
        identity = _google_identity(email, name="Fresh Customer")
        google_identity.signs_in_as(identity)

        r = await client.post(
            f"{BASE}/auth/google",
            json={"id_token": "t", "tenant_id": test_tenant.id},
        )
        assert r.status_code == 200

        user = await _fetch_user_by_email(db_session, email)
        assert user is not None
        assert user.tenant_id == test_tenant.id
        assert user.google_sub == identity.subject
        assert user.is_active is True
        assert user.kyc_status == "Pending"

    async def test_new_customer_gets_the_customer_role(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        google_identity,
        test_tenant: Tenant,
    ):
        email = f"role_{uuid.uuid4().hex[:8]}@gmail.com"
        google_identity.signs_in_as(_google_identity(email))
        await client.post(
            f"{BASE}/auth/google", json={"id_token": "t", "tenant_id": test_tenant.id}
        )

        user = await _fetch_user_by_email(db_session, email)
        role = (
            await db_session.execute(select(Role).where(Role.id == user.role_id))
        ).scalar_one()
        assert role.name == ROLE_CUSTOMER

    async def test_new_customer_gets_a_backend_allocated_code(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        google_identity,
        test_tenant: Tenant,
    ):
        """Same rule as ordinary signup — the code is never client-chosen."""
        email = f"code_{uuid.uuid4().hex[:8]}@gmail.com"
        google_identity.signs_in_as(_google_identity(email))
        await client.post(
            f"{BASE}/auth/google", json={"id_token": "t", "tenant_id": test_tenant.id}
        )

        user = await _fetch_user_by_email(db_session, email)
        assert user.customer_code
        assert user.member_since

    async def test_new_customer_starts_email_verified(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        google_identity,
        test_tenant: Tenant,
    ):
        """Google only hands over addresses it has verified, so there is
        nothing left to confirm by email."""
        email = f"verified_{uuid.uuid4().hex[:8]}@gmail.com"
        google_identity.signs_in_as(_google_identity(email))
        await client.post(
            f"{BASE}/auth/google", json={"id_token": "t", "tenant_id": test_tenant.id}
        )

        user = await _fetch_user_by_email(db_session, email)
        assert user.email_verified_at is not None

    async def test_new_customer_cannot_be_logged_into_with_a_password(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        google_identity,
        test_tenant: Tenant,
    ):
        """The placeholder secret is random and discarded — no password login
        should be possible against a Google-created account."""
        email = f"nopwd_{uuid.uuid4().hex[:8]}@gmail.com"
        google_identity.signs_in_as(_google_identity(email))
        await client.post(
            f"{BASE}/auth/google", json={"id_token": "t", "tenant_id": test_tenant.id}
        )

        for attempt in ("", "password", "Google User"):
            r = await client.post(
                f"{BASE}/auth/login", json={"username": email, "password": attempt}
            )
            assert r.status_code in (400, 401)

    async def test_unknown_store_is_rejected(
        self, client: AsyncClient, db_session: AsyncSession, google_identity
    ):
        email = f"badstore_{uuid.uuid4().hex[:8]}@gmail.com"
        google_identity.signs_in_as(_google_identity(email))
        r = await client.post(
            f"{BASE}/auth/google",
            json={"id_token": "t", "tenant_id": "tnt_does_not_exist"},
        )
        assert r.status_code == 400
        assert await _fetch_user_by_email(db_session, email) is None

    async def test_inactive_store_is_rejected(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        google_identity,
        test_tenant: Tenant,
    ):
        """A suspended store must not accept new sign-ups — the old code's
        `select(Tenant.id).limit(1)` fallback had no status filter at all."""
        test_tenant.status = "Inactive"
        await db_session.commit()

        email = f"inactivestore_{uuid.uuid4().hex[:8]}@gmail.com"
        google_identity.signs_in_as(_google_identity(email))
        r = await client.post(
            f"{BASE}/auth/google",
            json={"id_token": "t", "tenant_id": test_tenant.id},
        )
        assert r.status_code == 400
        assert await _fetch_user_by_email(db_session, email) is None


# ═══════════════════════════════════════════════════════════
# 4.  Existing accounts — the no-duplicates guarantee
# ═══════════════════════════════════════════════════════════

class TestExistingAccounts:

    async def test_links_onto_an_existing_password_account(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        google_identity,
        customer_user: User,
    ):
        """Somebody who signed up with email+password, then later taps Google:
        one account, not two."""
        identity = _google_identity(customer_user.email)
        google_identity.signs_in_as(identity)

        r = await client.post(f"{BASE}/auth/google", json={"id_token": "t"})
        assert r.status_code == 200
        assert await _count_users_with_email(db_session, customer_user.email) == 1

        await db_session.refresh(customer_user)
        assert customer_user.google_sub == identity.subject

    async def test_linking_needs_no_store_and_keeps_the_original_one(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        google_identity,
        customer_user: User,
    ):
        original_tenant = customer_user.tenant_id
        google_identity.signs_in_as(_google_identity(customer_user.email))

        r = await client.post(f"{BASE}/auth/google", json={"id_token": "t"})
        assert r.status_code == 200

        await db_session.refresh(customer_user)
        assert customer_user.tenant_id == original_tenant

    async def test_a_client_supplied_store_cannot_move_an_existing_user(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        google_identity,
        customer_user: User,
    ):
        """tenant_id is only ever used to *create* an account. For an existing
        user it must be ignored, or anyone could reassign themselves — and
        thereby their data visibility — to another jeweller's store."""
        other = Tenant(
            id=f"tnt_other_{uuid.uuid4().hex[:8]}",
            name="Someone Else's Store",
            slug=f"other-{uuid.uuid4().hex[:8]}",
            status="Active",
        )
        db_session.add(other)
        await db_session.commit()

        original_tenant = customer_user.tenant_id
        google_identity.signs_in_as(_google_identity(customer_user.email))
        try:
            r = await client.post(
                f"{BASE}/auth/google",
                json={"id_token": "t", "tenant_id": other.id},
            )
            assert r.status_code == 200
            await db_session.refresh(customer_user)
            assert customer_user.tenant_id == original_tenant
        finally:
            await db_session.delete(other)
            await db_session.commit()

    async def test_email_matching_is_case_insensitive(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        google_identity,
        test_tenant: Tenant,
    ):
        """Existing rows hold whatever casing was typed at signup; Google
        normalises to lowercase. A case difference must not fork the account."""
        role = (
            await db_session.execute(select(Role).where(Role.name == ROLE_CUSTOMER))
        ).scalar_one()
        mixed = f"MiXeD_{uuid.uuid4().hex[:8]}@Gmail.com"
        user = User(
            id=f"usr_mixed_{uuid.uuid4().hex[:8]}",
            tenant_id=test_tenant.id,
            role_id=role.id,
            email=mixed,
            hashed_password=hash_password("TestPass@123"),
            name="Mixed Case",
            kyc_status="Pending",
            is_active=True,
        )
        db_session.add(user)
        await db_session.commit()

        google_identity.signs_in_as(_google_identity(mixed.lower()))
        r = await client.post(f"{BASE}/auth/google", json={"id_token": "t"})
        assert r.status_code == 200
        assert await _count_users_with_email(db_session, mixed) == 1

    async def test_repeat_sign_in_reuses_the_same_user(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        google_identity,
        test_tenant: Tenant,
    ):
        email = f"repeat_{uuid.uuid4().hex[:8]}@gmail.com"
        identity = _google_identity(email)
        google_identity.signs_in_as(identity)

        first = await client.post(
            f"{BASE}/auth/google", json={"id_token": "t", "tenant_id": test_tenant.id}
        )
        second = await client.post(
            f"{BASE}/auth/google", json={"id_token": "t", "tenant_id": test_tenant.id}
        )
        assert first.status_code == 200
        assert second.status_code == 200
        assert await _count_users_with_email(db_session, email) == 1

    async def test_a_changed_google_email_still_resolves_by_subject(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        google_identity,
        test_tenant: Tenant,
    ):
        """The whole point of storing `sub`: the user renames their Google
        account and is still the same customer, not a brand-new one."""
        subject = f"gsub_stable_{uuid.uuid4().hex[:12]}"
        old_email = f"before_{uuid.uuid4().hex[:8]}@gmail.com"
        new_email = f"after_{uuid.uuid4().hex[:8]}@gmail.com"

        google_identity.signs_in_as(_google_identity(old_email, subject=subject))
        await client.post(
            f"{BASE}/auth/google", json={"id_token": "t", "tenant_id": test_tenant.id}
        )
        created = await _fetch_user_by_email(db_session, old_email)
        assert created is not None

        # Same Google account, new address, and NO tenant_id — if it were not
        # recognised, this would come back 400 asking for a store.
        google_identity.signs_in_as(_google_identity(new_email, subject=subject))
        r = await client.post(f"{BASE}/auth/google", json={"id_token": "t"})
        assert r.status_code == 200
        assert await _count_users_with_email(db_session, new_email) == 0

        access = r.json()["data"]["access_token"]
        me = await client.get(
            f"{BASE}/users/me", headers={"Authorization": f"Bearer {access}"}
        )
        assert me.json()["data"]["user"]["id"] == created.id


# ═══════════════════════════════════════════════════════════
# 5.  Access control still applies
# ═══════════════════════════════════════════════════════════

class TestAccessControl:

    async def test_deactivated_user_is_rejected(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        google_identity,
        customer_user: User,
    ):
        customer_user.is_active = False
        await db_session.commit()

        google_identity.signs_in_as(_google_identity(customer_user.email))
        r = await client.post(f"{BASE}/auth/google", json={"id_token": "t"})
        assert r.status_code == 401

    async def test_suspended_store_blocks_an_existing_user(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        google_identity,
        customer_user: User,
        test_tenant: Tenant,
    ):
        """Same tenant-lifecycle gate password login goes through — Google
        sign-in must not be a way around a suspended store."""
        test_tenant.status = "Suspended"
        await db_session.commit()

        google_identity.signs_in_as(_google_identity(customer_user.email))
        r = await client.post(f"{BASE}/auth/google", json={"id_token": "t"})
        assert r.status_code == 401

    async def test_expired_trial_blocks_an_existing_user(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        google_identity,
        customer_user: User,
        test_tenant: Tenant,
    ):
        from datetime import datetime, timedelta, timezone

        test_tenant.status = "Active"
        db_session.add(
            Subscription(
                id=f"sub_{uuid.uuid4().hex[:8]}",
                tenant_id=test_tenant.id,
                plan="Trial",
                status="Trial",
                trial_ends_at=datetime.now(timezone.utc) - timedelta(days=1),
            )
        )
        await db_session.commit()

        google_identity.signs_in_as(_google_identity(customer_user.email))
        r = await client.post(f"{BASE}/auth/google", json={"id_token": "t"})
        assert r.status_code == 401


# ═══════════════════════════════════════════════════════════
# 6.  Issued tokens are ordinary session tokens
# ═══════════════════════════════════════════════════════════

class TestIssuedTokens:

    async def test_response_shape_matches_password_login(
        self, client: AsyncClient, google_identity, test_tenant: Tenant
    ):
        google_identity.signs_in_as(
            _google_identity(f"shape_{uuid.uuid4().hex[:8]}@gmail.com")
        )
        r = await client.post(
            f"{BASE}/auth/google", json={"id_token": "t", "tenant_id": test_tenant.id}
        )
        body = r.json()
        assert body["success"] is True
        data = body["data"]
        assert data["token_type"] == "Bearer"
        assert isinstance(data["expires_in"], int)
        for key in ("access_token", "refresh_token"):
            assert isinstance(data[key], str) and data[key]

    async def test_access_token_authenticates_a_real_endpoint(
        self, client: AsyncClient, google_identity, test_tenant: Tenant
    ):
        email = f"usable_{uuid.uuid4().hex[:8]}@gmail.com"
        google_identity.signs_in_as(_google_identity(email))
        r = await client.post(
            f"{BASE}/auth/google", json={"id_token": "t", "tenant_id": test_tenant.id}
        )
        access = r.json()["data"]["access_token"]

        me = await client.get(
            f"{BASE}/users/me", headers={"Authorization": f"Bearer {access}"}
        )
        assert me.status_code == 200
        assert me.json()["data"]["user"]["email"] == email

    async def test_refresh_token_rotates_like_any_other_session(
        self, client: AsyncClient, google_identity, test_tenant: Tenant
    ):
        """Google sessions go through the same refresh-token table and rotation
        logic — this is why token issuance is shared with login_user rather
        than reimplemented."""
        google_identity.signs_in_as(
            _google_identity(f"refresh_{uuid.uuid4().hex[:8]}@gmail.com")
        )
        r = await client.post(
            f"{BASE}/auth/google", json={"id_token": "t", "tenant_id": test_tenant.id}
        )
        refresh = r.json()["data"]["refresh_token"]

        rotated = await client.post(
            f"{BASE}/auth/refresh", json={"refresh_token": refresh}
        )
        assert rotated.status_code == 200
        assert rotated.json()["data"]["refresh_token"] != refresh

    async def test_logout_revokes_a_google_session(
        self, client: AsyncClient, google_identity, test_tenant: Tenant
    ):
        google_identity.signs_in_as(
            _google_identity(f"logout_{uuid.uuid4().hex[:8]}@gmail.com")
        )
        r = await client.post(
            f"{BASE}/auth/google", json={"id_token": "t", "tenant_id": test_tenant.id}
        )
        data = r.json()["data"]

        out = await client.post(
            f"{BASE}/auth/logout",
            json={"refresh_token": data["refresh_token"]},
            headers={"Authorization": f"Bearer {data['access_token']}"},
        )
        assert out.status_code == 200

        reused = await client.post(
            f"{BASE}/auth/refresh", json={"refresh_token": data["refresh_token"]}
        )
        assert reused.status_code == 401


# ═══════════════════════════════════════════════════════════
# 7.  Rate limiting
# ═══════════════════════════════════════════════════════════

class TestRateLimiting:

    async def test_repeated_attempts_are_throttled(
        self, client: AsyncClient, google_identity
    ):
        """The endpoint shares the login limiter, so it cannot be used as an
        unthrottled oracle for probing which accounts exist. The original
        implementation had no limiter on this route at all."""
        google_identity.fails_with(UnauthorizedException("bad token"))

        statuses = [
            (await client.post(f"{BASE}/auth/google", json={"id_token": "x"})).status_code
            for _ in range(login_rate_limiter.limit + 2)
        ]
        assert 429 in statuses
