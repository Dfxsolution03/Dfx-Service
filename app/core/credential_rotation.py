"""
Temporary, startup-gated SuperAdmin credential rotation.

Runs from app.main's lifespan(), and ONLY does anything when
settings.ROTATE_SUPERADMIN_CREDENTIALS is True — which is False in every
environment unless explicitly set. Reads the target email/password from
settings.NEW_SUPERADMIN_EMAIL / settings.NEW_SUPERADMIN_PASSWORD, which are
themselves sourced only from environment variables (see app/core/config.py)
and never committed anywhere.

Safety properties:
  - Touches exactly one row: the existing SuperAdmin User, identified by
    role, never by a hardcoded id/email.
  - Aborts with NO write if there isn't exactly one SuperAdmin account.
  - Aborts with NO write if the target email already belongs to a
    different existing user (no duplicate, no silent takeover).
  - Idempotent: if the account already has the target email and the target
    password already verifies, it's a no-op — safe to leave the flag on
    across more than one restart without repeated writes.
  - Reuses the exact same hashing implementation (app.core.security.
    hash_password) as normal signup/password-reset — no parallel hashing
    path introduced.
  - Never logs the password, in success, no-op, or error paths.

Not exposed via any API route — this only runs from process startup.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import ROLE_SUPERADMIN
from app.core.logging import logger
from app.core.security import hash_password, verify_password
from app.models.auth import Role, User


async def rotate_superadmin_credentials(db: AsyncSession) -> None:
    if not settings.ROTATE_SUPERADMIN_CREDENTIALS:
        return

    new_email = (settings.NEW_SUPERADMIN_EMAIL or "").strip()
    new_password = settings.NEW_SUPERADMIN_PASSWORD or ""

    if not new_email or not new_password:
        logger.error(
            "[credential_rotation] ROTATE_SUPERADMIN_CREDENTIALS=true but "
            "NEW_SUPERADMIN_EMAIL/NEW_SUPERADMIN_PASSWORD are not both set — aborting, no changes made."
        )
        return

    role_stmt = select(Role).where(Role.name == ROLE_SUPERADMIN)
    role = (await db.execute(role_stmt)).scalar_one_or_none()
    if not role:
        logger.error(f"[credential_rotation] No '{ROLE_SUPERADMIN}' role exists — aborting, no changes made.")
        return

    sa_stmt = select(User).where(User.role_id == role.id)
    superadmins = (await db.execute(sa_stmt)).scalars().all()

    if len(superadmins) != 1:
        logger.error(
            f"[credential_rotation] Expected exactly 1 SuperAdmin account, found {len(superadmins)} — "
            "aborting, no changes made."
        )
        return

    target = superadmins[0]

    # Conflict check: the target email must not already belong to a
    # *different* user (Admin/Staff/Customer or otherwise).
    conflict_stmt = select(User).where(User.email == new_email)
    conflict = (await db.execute(conflict_stmt)).scalar_one_or_none()
    if conflict and conflict.id != target.id:
        logger.error(
            f"[credential_rotation] Target email is already in use by a different account "
            f"(id={conflict.id}) — aborting, no changes made."
        )
        return

    email_already_correct = target.email == new_email
    password_already_correct = verify_password(new_password, target.hashed_password)

    if email_already_correct and password_already_correct:
        logger.info(f"[credential_rotation] SuperAdmin id={target.id} already matches target credentials — no-op.")
        return

    if not email_already_correct:
        target.email = new_email
    if not password_already_correct:
        target.hashed_password = hash_password(new_password)

    await db.commit()
    logger.info(
        f"[credential_rotation] SuperAdmin id={target.id} credentials rotated successfully "
        f"(email_changed={not email_already_correct}, password_changed={not password_already_correct})."
    )
