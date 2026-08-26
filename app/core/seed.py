import asyncio
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionFactory
from app.core.security import hash_password
from app.core.constants import (
    ROLE_CUSTOMER,
    ROLE_STAFF,
    ROLE_ADMIN,
    ROLE_SUPERADMIN,
    ROLE_PERMISSIONS_MAP,
)
from app.models.auth import Tenant, Subscription, Role, Permission, RolePermission, User
from app.models.customer import Branch
from app.models.scheme import Scheme, SchemeTier


async def seed_database() -> None:
    """Seed default roles, permissions, role-permission mappings, default tenant, branches, and SuperAdmin."""
    async with AsyncSessionFactory() as db:
        print("--> Seeding Database Default Records...")

        # 1. Seed Roles
        roles_data = [
            (ROLE_CUSTOMER, "End customer micro-savings user"),
            (ROLE_STAFF, "Store employee recording offline transactions"),
            (ROLE_ADMIN, "Jeweller store owner managing store schemes & reports"),
            (ROLE_SUPERADMIN, "Platform Super Admin managing multi-tenant SaaS"),
        ]

        roles_dict = {}
        for role_name, desc in roles_data:
            stmt = select(Role).where(Role.name == role_name)
            existing_role = (await db.execute(stmt)).scalar_one_or_none()
            if not existing_role:
                role_id = f"rol_{role_name.lower()}"
                new_role = Role(id=role_id, name=role_name, description=desc)
                db.add(new_role)
                await db.flush()
                roles_dict[role_name] = new_role
            else:
                roles_dict[role_name] = existing_role

        # 2. Seed Permissions & Role Mappings
        all_perm_codes = set()
        for perms in ROLE_PERMISSIONS_MAP.values():
            all_perm_codes.update(perms)

        perm_dict = {}
        for code in all_perm_codes:
            stmt = select(Permission).where(Permission.code == code)
            existing_perm = (await db.execute(stmt)).scalar_one_or_none()
            if not existing_perm:
                perm_id = f"prm_{code.replace(':', '_')}"
                new_perm = Permission(id=perm_id, code=code, description=f"Permission for {code}")
                db.add(new_perm)
                await db.flush()
                perm_dict[code] = new_perm
            else:
                perm_dict[code] = existing_perm

        # Seed RolePermissions
        for role_name, perm_codes in ROLE_PERMISSIONS_MAP.items():
            role_obj = roles_dict[role_name]
            for code in perm_codes:
                perm_obj = perm_dict[code]
                stmt_rp = select(RolePermission).where(
                    RolePermission.role_id == role_obj.id,
                    RolePermission.permission_id == perm_obj.id,
                )
                if not (await db.execute(stmt_rp)).scalar_one_or_none():
                    db.add(RolePermission(role_id=role_obj.id, permission_id=perm_obj.id))

        # 3. Seed Default Active Tenant (Sri Krishna Jewellers)
        tenant_id = "tnt_default_sk"
        stmt_tnt = select(Tenant).where(Tenant.id == tenant_id)
        existing_tenant = (await db.execute(stmt_tnt)).scalar_one_or_none()
        if not existing_tenant:
            tenant = Tenant(
                id=tenant_id,
                name="Sri Krishna Jewellers",
                slug="sri-krishna-jewellers",
                status="Active",
            )
            db.add(tenant)
            await db.flush()

            sub = Subscription(
                id="sub_default_sk",
                tenant_id=tenant.id,
                plan="Business",
                status="Active",
            )
            db.add(sub)

        # 4. Seed Default Tenant Branches (SCR-CUST-08)
        branches_data = [
            ("brn_sk_01", "MG Road Flagship Branch", "102 MG Road, Opp Metro Station, Bengaluru - 560001", "080-25590001", 12.9716, 77.5946),
            ("brn_sk_02", "Indiranagar Boutique Branch", "456 100ft Road, Indiranagar, Bengaluru - 560038", "080-25200002", 12.9784, 77.6408),
        ]
        for brn_id, b_name, b_addr, b_phone, b_lat, b_lng in branches_data:
            stmt_brn = select(Branch).where(Branch.id == brn_id)
            if not (await db.execute(stmt_brn)).scalar_one_or_none():
                db.add(
                    Branch(
                        id=brn_id,
                        tenant_id=tenant_id,
                        name=b_name,
                        address=b_addr,
                        phone=b_phone,
                        latitude=b_lat,
                        longitude=b_lng,
                        is_active=True,
                    )
                )

        # 5. Seed SuperAdmin User using environment settings
        superadmin_email = settings.SUPERADMIN_EMAIL
        stmt_sa = select(User).where(User.email == superadmin_email)
        existing_sa = (await db.execute(stmt_sa)).scalar_one_or_none()
        superadmin_id = existing_sa.id if existing_sa else "usr_superadmin"
        if not existing_sa:
            sa_user = User(
                id="usr_superadmin",
                tenant_id=None,  # Nullable tenant_id for SuperAdmin
                role_id=roles_dict[ROLE_SUPERADMIN].id,
                email=superadmin_email,
                phone="0000000000",
                hashed_password=hash_password(settings.SUPERADMIN_PASSWORD),
                name="Platform Super Admin",
                kyc_status="Verified",
                member_since="January 2026",
                is_active=True,
            )
            db.add(sa_user)
            await db.flush()  # make usr_superadmin FK-usable for the default scheme below

        # 6. Seed the default multi-tier scheme "Monthly Gold Saving Plan".
        # Idempotent, keyed on (tenant_id, name); the five tiers are added only
        # when missing (keyed on their amount+duration), so re-running the seed
        # never duplicates the plan or its tiers. Maturity is amount x months —
        # no bonus/interest. The scheme-level monthly_amount/duration_months hold
        # the smallest tier so any legacy (tier-less) enrollment falls back sanely.
        default_scheme_name = "Monthly Gold Saving Plan"
        default_scheme = (await db.execute(
            select(Scheme).where(
                Scheme.tenant_id == tenant_id, Scheme.name == default_scheme_name
            )
        )).scalar_one_or_none()
        if not default_scheme:
            default_scheme = Scheme(
                id="sch_default_gold",
                tenant_id=tenant_id,
                name=default_scheme_name,
                description="Fixed monthly savings plan. Pick a tier; maturity = monthly amount x months.",
                monthly_amount=1000.0,
                duration_months=12,
                bonus_description=None,
                is_active=True,
                created_by=superadmin_id,
            )
            db.add(default_scheme)
            await db.flush()

        default_tiers = [(1000.0, 12), (2000.0, 12), (5000.0, 12), (10000.0, 12), (15000.0, 12)]
        existing_tiers = (await db.execute(
            select(SchemeTier).where(SchemeTier.scheme_id == default_scheme.id)
        )).scalars().all()
        have = {(t.monthly_amount, t.duration_months) for t in existing_tiers}
        for i, (amt, dur) in enumerate(default_tiers, start=1):
            if (amt, dur) not in have:
                db.add(SchemeTier(
                    id=f"str_default_{i:02d}",
                    scheme_id=default_scheme.id,
                    monthly_amount=amt,
                    duration_months=dur,
                    is_active=True,
                ))

        await db.commit()
        print("--> Database Seeding Complete!")


if __name__ == "__main__":
    asyncio.run(seed_database())
