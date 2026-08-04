import uuid
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User, Tenant
from app.models.customer import KYCRecord, UserAddress, Branch
from app.repositories.customer_repository import CustomerRepository
from app.repositories.audit_repository import AuditRepository
from app.exceptions.base import (
    ResourceNotFoundException,
    ConflictException,
    ValidationException,
    ForbiddenException,
)
from app.schemas.customer import (
    ProfileUpdateRequest,
    CustomerProfileResponse,
    KYCSubmitRequest,
    KYCResponse,
    KYCRejectRequest,
    AdminKYCResponse,
    AddressCreateRequest,
    AddressUpdateRequest,
    AddressResponse,
    BranchResponseItem,
)


class CustomerService:
    @staticmethod
    async def get_profile(
        db: AsyncSession, current_user: User
    ) -> CustomerProfileResponse:
        """Fetch customer profile details along with store tenant information."""
        tenant_name = "Platform SuperAdmin"
        if current_user.tenant_id:
            tenant = await CustomerRepository.get_tenant_by_id(db, current_user.tenant_id)
            if tenant:
                tenant_name = tenant.name

        return CustomerProfileResponse(
            id=current_user.id,
            tenant_id=current_user.tenant_id,
            tenant_name=tenant_name,
            name=current_user.name,
            email=current_user.email,
            phone=current_user.phone,
            kyc_status=current_user.kyc_status,
            member_since=current_user.member_since or "July 2026",
            avatar_url=current_user.avatar_url,
        )

    @staticmethod
    async def update_profile(
        db: AsyncSession, current_user: User, req: ProfileUpdateRequest
    ) -> CustomerProfileResponse:
        """Update customer profile information."""
        before_state = {
            "name": current_user.name,
            "email": current_user.email,
            "phone": current_user.phone,
            "avatar_url": current_user.avatar_url,
        }

        # Validate duplicate email or phone
        if req.email and req.email != current_user.email:
            stmt_email = select(User).where(User.email == req.email, User.id != current_user.id)
            if (await db.execute(stmt_email)).scalar_one_or_none():
                raise ConflictException("An account with this email address already exists")
            current_user.email = req.email

        if req.phone and req.phone != current_user.phone:
            stmt_phone = select(User).where(User.phone == req.phone, User.id != current_user.id)
            if (await db.execute(stmt_phone)).scalar_one_or_none():
                raise ConflictException("An account with this phone number already exists")
            current_user.phone = req.phone

        if req.name:
            current_user.name = req.name

        if req.avatar_url is not None:
            current_user.avatar_url = req.avatar_url

        after_state = {
            "name": current_user.name,
            "email": current_user.email,
            "phone": current_user.phone,
            "avatar_url": current_user.avatar_url,
        }

        # Emit Audit Log
        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="PROFILE_UPDATE",
            target_entity="users",
            target_id=current_user.id,
            before_state=before_state,
            after_state=after_state,
        )

        await db.commit()
        await db.refresh(current_user)

        return await CustomerService.get_profile(db, current_user)

    @staticmethod
    async def get_kyc(
        db: AsyncSession, current_user: User
    ) -> Optional[KYCResponse]:
        """Fetch customer's current KYC document status."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        record = await CustomerRepository.get_kyc_record(db, current_user.id, current_user.tenant_id)
        if not record:
            return None

        return KYCResponse(
            id=record.id,
            user_id=record.user_id,
            doc_type=record.doc_type,
            doc_number=record.doc_number,
            status=record.status,
            verified_at=record.verified_at.isoformat() if record.verified_at else None,
            rejection_reason=record.rejection_reason,
        )

    @staticmethod
    async def submit_kyc(
        db: AsyncSession, current_user: User, req: KYCSubmitRequest
    ) -> KYCResponse:
        """Submit a new KYC verification document."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        # Check existing record
        existing = await CustomerRepository.get_kyc_record(db, current_user.id, current_user.tenant_id)
        if existing and existing.status == "Verified":
            raise ConflictException("Customer KYC document is already verified. Cannot resubmit.")

        kyc_id = f"kyc_{uuid.uuid4().hex[:12]}"
        new_record = KYCRecord(
            id=kyc_id,
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            doc_type=req.doc_type,
            doc_number=req.doc_number,
            status="Pending",
        )
        await CustomerRepository.create_kyc_record(db, new_record)

        # Update User KYC status
        current_user.kyc_status = "Pending"

        # Emit Audit Log
        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="KYC_SUBMIT",
            target_entity="kyc_records",
            target_id=kyc_id,
            before_state=None,
            after_state={"doc_type": req.doc_type, "doc_number": req.doc_number, "status": "Pending"},
        )

        await db.commit()

        return KYCResponse(
            id=new_record.id,
            user_id=new_record.user_id,
            doc_type=new_record.doc_type,
            doc_number=new_record.doc_number,
            status=new_record.status,
            verified_at=None,
            rejection_reason=None,
        )

    # ─── Admin: KYC Review ───

    @staticmethod
    def _to_admin_kyc_response(record: KYCRecord) -> AdminKYCResponse:
        return AdminKYCResponse(
            id=record.id,
            tenant_id=record.tenant_id,
            user_id=record.user_id,
            customer_name=record.user.name,
            customer_email=record.user.email,
            customer_phone=record.user.phone,
            doc_type=record.doc_type,
            doc_number=record.doc_number,
            status=record.status,
            verified_at=record.verified_at.isoformat() if record.verified_at else None,
            rejection_reason=record.rejection_reason,
            created_at=record.created_at.isoformat(),
        )

    @staticmethod
    async def get_kyc_records_for_admin(
        db: AsyncSession, current_user: User
    ) -> List[AdminKYCResponse]:
        """Admin: list all KYC submissions for the tenant, newest first."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        records = await CustomerRepository.get_kyc_records_by_tenant(db, current_user.tenant_id)
        return [CustomerService._to_admin_kyc_response(r) for r in records]

    @staticmethod
    async def get_kyc_record_for_admin(
        db: AsyncSession, current_user: User, kyc_id: str
    ) -> AdminKYCResponse:
        """Admin: fetch a single KYC submission by ID, scoped to the admin's tenant."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        record = await CustomerRepository.get_kyc_record_by_id(db, kyc_id, current_user.tenant_id)
        if not record:
            raise ResourceNotFoundException(f"KYC record ID '{kyc_id}' not found")
        return CustomerService._to_admin_kyc_response(record)

    @staticmethod
    async def approve_kyc(
        db: AsyncSession, current_user: User, kyc_id: str
    ) -> AdminKYCResponse:
        """Admin approves a Pending KYC submission, verifying the customer's identity."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        record = await CustomerRepository.get_kyc_record_by_id(db, kyc_id, current_user.tenant_id)
        if not record:
            raise ResourceNotFoundException(f"KYC record ID '{kyc_id}' not found")
        if record.status != "Pending":
            raise ConflictException(
                f"KYC record is already '{record.status}'. Only Pending submissions can be reviewed."
            )

        before_state = {"status": record.status}

        record.status = "Verified"
        record.verified_at = datetime.now(timezone.utc)
        record.rejection_reason = None
        record.user.kyc_status = "Verified"

        after_state = {"status": record.status, "verified_at": record.verified_at.isoformat()}

        # Emit Audit Log
        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="KYC_APPROVE",
            target_entity="kyc_records",
            target_id=kyc_id,
            before_state=before_state,
            after_state=after_state,
        )

        await db.commit()
        await db.refresh(record)

        return CustomerService._to_admin_kyc_response(record)

    @staticmethod
    async def reject_kyc(
        db: AsyncSession, current_user: User, kyc_id: str, req: KYCRejectRequest
    ) -> AdminKYCResponse:
        """Admin rejects a Pending KYC submission with a documented reason."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        record = await CustomerRepository.get_kyc_record_by_id(db, kyc_id, current_user.tenant_id)
        if not record:
            raise ResourceNotFoundException(f"KYC record ID '{kyc_id}' not found")
        if record.status != "Pending":
            raise ConflictException(
                f"KYC record is already '{record.status}'. Only Pending submissions can be reviewed."
            )

        before_state = {"status": record.status}

        record.status = "Rejected"
        record.rejection_reason = req.reason
        record.user.kyc_status = "Rejected"

        after_state = {"status": record.status, "rejection_reason": record.rejection_reason}

        # Emit Audit Log
        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="KYC_REJECT",
            target_entity="kyc_records",
            target_id=kyc_id,
            before_state=before_state,
            after_state=after_state,
        )

        await db.commit()
        await db.refresh(record)

        return CustomerService._to_admin_kyc_response(record)

    @staticmethod
    async def get_addresses(
        db: AsyncSession, current_user: User
    ) -> List[AddressResponse]:
        """List all customer saved addresses."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        addresses = await CustomerRepository.get_user_addresses(db, current_user.id, current_user.tenant_id)
        return [AddressResponse.model_validate(a) for a in addresses]

    @staticmethod
    async def add_address(
        db: AsyncSession, current_user: User, req: AddressCreateRequest
    ) -> AddressResponse:
        """Add a new customer shipping address."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        existing_addresses = await CustomerRepository.get_user_addresses(db, current_user.id, current_user.tenant_id)
        is_first = len(existing_addresses) == 0
        should_be_default = req.is_default or is_first

        if should_be_default:
            await CustomerRepository.unset_default_addresses(db, current_user.id, current_user.tenant_id)

        address_id = f"addr_{uuid.uuid4().hex[:12]}"
        address = UserAddress(
            id=address_id,
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            name=req.name,
            phone=req.phone,
            house=req.house,
            street=req.street,
            area=req.area,
            city=req.city,
            state=req.state,
            pincode=req.pincode,
            country="India",
            type=req.type,
            is_default=should_be_default,
        )
        await CustomerRepository.create_address(db, address)

        # Emit Audit Log
        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="ADDRESS_CREATE",
            target_entity="user_addresses",
            target_id=address_id,
            before_state=None,
            after_state={"name": req.name, "pincode": req.pincode, "is_default": should_be_default},
        )

        await db.commit()
        await db.refresh(address)

        return AddressResponse.model_validate(address)

    @staticmethod
    async def update_address(
        db: AsyncSession, current_user: User, address_id: str, req: AddressUpdateRequest
    ) -> AddressResponse:
        """Update an existing customer address."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        address = await CustomerRepository.get_address_by_id(
            db, address_id=address_id, user_id=current_user.id, tenant_id=current_user.tenant_id
        )
        if not address:
            raise ResourceNotFoundException(f"Address ID '{address_id}' not found")

        before_state = {"name": address.name, "house": address.house, "is_default": address.is_default}

        if req.is_default:
            await CustomerRepository.unset_default_addresses(db, current_user.id, current_user.tenant_id)
            address.is_default = True

        for field in ["name", "phone", "house", "street", "area", "city", "state", "pincode", "type"]:
            val = getattr(req, field, None)
            if val is not None:
                setattr(address, field, val)

        after_state = {"name": address.name, "house": address.house, "is_default": address.is_default}

        # Emit Audit Log
        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="ADDRESS_UPDATE",
            target_entity="user_addresses",
            target_id=address.id,
            before_state=before_state,
            after_state=after_state,
        )

        await db.commit()
        await db.refresh(address)

        return AddressResponse.model_validate(address)

    @staticmethod
    async def delete_address(
        db: AsyncSession, current_user: User, address_id: str
    ) -> None:
        """Delete a customer address."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        address = await CustomerRepository.get_address_by_id(
            db, address_id=address_id, user_id=current_user.id, tenant_id=current_user.tenant_id
        )
        if not address:
            raise ResourceNotFoundException(f"Address ID '{address_id}' not found")

        was_default = address.is_default
        await CustomerRepository.delete_address(db, address)

        # If the default address was removed, promote the next most recent
        # remaining address so the customer always has a default when possible.
        # Session autoflush is disabled (see core/database.py), so the pending
        # delete must be flushed before re-querying or it still shows up here.
        if was_default:
            await db.flush()
            remaining = await CustomerRepository.get_user_addresses(
                db, current_user.id, current_user.tenant_id
            )
            if remaining:
                remaining[0].is_default = True

        # Emit Audit Log
        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="ADDRESS_DELETE",
            target_entity="user_addresses",
            target_id=address_id,
            before_state={"name": address.name, "pincode": address.pincode},
            after_state=None,
        )

        await db.commit()

    @staticmethod
    async def set_default_address(
        db: AsyncSession, current_user: User, address_id: str
    ) -> AddressResponse:
        """Set a customer address as the primary default address."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        address = await CustomerRepository.get_address_by_id(
            db, address_id=address_id, user_id=current_user.id, tenant_id=current_user.tenant_id
        )
        if not address:
            raise ResourceNotFoundException(f"Address ID '{address_id}' not found")

        await CustomerRepository.unset_default_addresses(db, current_user.id, current_user.tenant_id)
        address.is_default = True

        # Emit Audit Log
        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="ADDRESS_SET_DEFAULT",
            target_entity="user_addresses",
            target_id=address_id,
            before_state=None,
            after_state={"is_default": True},
        )

        await db.commit()
        await db.refresh(address)

        return AddressResponse.model_validate(address)

    @staticmethod
    async def get_branches(
        db: AsyncSession, current_user: User
    ) -> List[BranchResponseItem]:
        """List active store branches for customer's tenant."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        branches = await CustomerRepository.get_tenant_branches(db, current_user.tenant_id)
        return [BranchResponseItem.model_validate(b) for b in branches]
