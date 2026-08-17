import math
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.models.auth import User, Tenant, RefreshToken
from app.models.customer import KYCRecord, UserAddress, Branch, KycDocument
from app.models.payment import STATUS_SUCCESS as PAYMENT_SUCCESS
from app.core.constants import SALE_STATUS_COMPLETED
from app.repositories.customer_repository import CustomerRepository
from app.repositories.audit_repository import AuditRepository
from app.repositories.enrollment_repository import EnrollmentRepository, SchemeRedemptionRepository
from app.repositories.passbook_repository import PassbookRepository
from app.repositories.payment_repository import PaymentRepository
from app.repositories.billing_repository import (
    SaleRepository,
    SalePaymentRepository,
    SaleReturnRepository,
)
from app.services.enrollment_service import SchemeBalanceService

# Upper bound on how many contribution / purchase rows one Customer 360 read
# returns. A memory backstop for an unusually long-lived customer, not a
# business rule — the underlying ledgers stay complete.
OVERVIEW_ROW_CAP = 500
from app.exceptions.base import (
    ResourceNotFoundException,
    ConflictException,
    ValidationException,
    ForbiddenException,
    UnauthorizedException,
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
    ChangePasswordRequest,
    KycDocumentSubmitRequest,
    KycDocumentResponse,
    AdminCustomerListItem,
    AdminCustomerDetailResponse,
    AdminCustomerPaginationInfo,
    CustomerOverviewResponse,
    CustomerOverviewProfile,
    CustomerOverviewKyc,
    CustomerOverviewEnrollment,
    CustomerOverviewContribution,
    CustomerOverviewRedemption,
    CustomerOverviewPurchase,
    CustomerOverviewPayment,
    CustomerOverviewReturn,
    CustomerOverviewTotals,
    CUSTOMER_TYPE_WALK_IN,
    CUSTOMER_TYPE_SCHEME,
    CUSTOMER_TYPE_HYBRID,
    TenantProfileResponse,
    TenantProfileUpdateRequest,
    BranchCreateRequest,
    BranchUpdateRequest,
    BranchStatusUpdateRequest,
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

    # ─── Phase 6A / Module 31: Change Password ───

    @staticmethod
    async def change_password(
        db: AsyncSession, current_user: User, req: ChangePasswordRequest
    ) -> None:
        """Verifies the old password against the stored hash, hashes the new
        password with the exact same core.security helpers auth_service.py
        already uses, revokes every existing refresh token for this user
        (reusing the same bulk-revoke pattern AuthService.reset_password
        already established for "password change invalidates all sessions"),
        and audit-logs the change. Does not touch auth_service.py or the
        login/JWT code path itself — this is a customer-in-session
        convenience action on top of the same primitives, not a new flow."""
        if not verify_password(req.old_password, current_user.hashed_password):
            raise UnauthorizedException("Current password is incorrect")

        current_user.hashed_password = hash_password(req.new_password)

        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == current_user.id, RefreshToken.is_revoked == False)  # noqa: E712
            .values(is_revoked=True)
        )

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="PASSWORD_CHANGE",
            target_entity="users",
            target_id=current_user.id,
            before_state=None,
            after_state=None,
        )

        await db.commit()

    # ─── Phase 6A / Module 31: KYC Document Submission (metadata only) ───

    @staticmethod
    async def submit_kyc_document(
        db: AsyncSession, current_user: User, req: KycDocumentSubmitRequest
    ) -> KycDocumentResponse:
        """Persists document metadata only — document_url is caller-supplied,
        no upload handling or storage provider call, per spec (explicitly
        deferred, same pattern as Tenant.logo_url in Module 29)."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        doc_id = f"kdoc_{uuid.uuid4().hex[:12]}"
        document = KycDocument(
            id=doc_id,
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            document_type=req.document_type,
            document_url=req.document_url,
            verification_status="PENDING",
        )
        await CustomerRepository.create_kyc_document(db, document)

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="KYC_DOCUMENT_SUBMIT",
            target_entity="kyc_documents",
            target_id=doc_id,
            before_state=None,
            after_state={"document_type": req.document_type},
        )

        await db.commit()
        await db.refresh(document)
        return KycDocumentResponse.model_validate(document)

    # ─── Phase 6C / Module 33: Admin Customer Management ───

    @staticmethod
    async def get_customers_for_admin(
        db: AsyncSession, current_user: User, page: int, limit: int, search: Optional[str]
    ) -> Tuple[List[AdminCustomerListItem], AdminCustomerPaginationInfo]:
        """Admin: paginated, searchable list of the tenant's own customers.
        Never accepts a tenant_id from the caller — always current_user's."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        customers, total = await CustomerRepository.get_customers_by_tenant(
            db, current_user.tenant_id, page, limit, search
        )
        total_pages = math.ceil(total / limit) if limit else 0
        pagination = AdminCustomerPaginationInfo(
            page=page, page_size=limit, total_items=total, total_pages=total_pages
        )

        # Derive the display type for this page in two batched queries (same rule
        # as Customer 360): enrollment only = SCHEME, sale only or neither =
        # WALK-IN, both = HYBRID. Never stored.
        ids = [c.id for c in customers]
        with_enr = await CustomerRepository.customer_ids_with_enrollment(db, ids, current_user.tenant_id)
        with_sale = await CustomerRepository.customer_ids_with_sale(db, ids, current_user.tenant_id)
        items = []
        for c in customers:
            item = AdminCustomerListItem.model_validate(c)
            if c.id in with_enr:
                item.customer_type = CUSTOMER_TYPE_HYBRID if c.id in with_sale else CUSTOMER_TYPE_SCHEME
            else:
                item.customer_type = CUSTOMER_TYPE_WALK_IN
            items.append(item)
        return items, pagination

    @staticmethod
    async def get_customer_detail_for_admin(
        db: AsyncSession, current_user: User, customer_id: str
    ) -> AdminCustomerDetailResponse:
        """Admin: single customer's profile + KYC status + enrollment/investment
        summary, own-tenant only. Reuses EnrollmentRepository/PaymentRepository's
        already-customer-scoped methods — same composition pattern as
        DashboardService, no new aggregation queries needed."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        customer = await CustomerRepository.get_customer_by_id_for_tenant(
            db, current_user.tenant_id, customer_id
        )
        if not customer:
            raise ResourceNotFoundException(f"Customer ID '{customer_id}' not found")

        enrollments = await EnrollmentRepository.get_enrollments_by_customer(
            db, current_user.tenant_id, customer_id
        )
        payments = await PaymentRepository.get_payments_by_customer(
            db, current_user.tenant_id, customer_id
        )
        total_invested = sum(p.amount for p in payments if p.payment_status == PAYMENT_SUCCESS)

        return AdminCustomerDetailResponse(
            id=customer.id,
            customer_code=customer.customer_code,
            name=customer.name,
            email=customer.email,
            phone=customer.phone,
            kyc_status=customer.kyc_status,
            member_since=customer.member_since,
            avatar_url=customer.avatar_url,
            is_active=customer.is_active,
            enrollment_count=len(enrollments),
            total_invested=total_invested,
        )

    # ─── Phase 1 — Customer 360 (read-only composition) ───

    @staticmethod
    async def get_customer_overview(
        db: AsyncSession, current_user: User, customer_id: str
    ) -> CustomerOverviewResponse:
        """One tenant-scoped read of everything the store knows about a customer.

        Strictly a COMPOSITION layer. Every financial figure below is read back
        from the module that owns it — scheme balances from SchemeBalanceService,
        sale totals from the Sale row's own derived caches, collections from the
        SalePayment ledger, refunds from SaleReturn. Nothing here recalculates
        money, and nothing here writes.
        """
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        tenant_id = current_user.tenant_id

        # Tenant- AND role-scoped: this reuses the same lookup the customer
        # detail endpoint uses, so another tenant's customer (or this tenant's
        # Admin/Staff account) can never be opened through Customer 360.
        customer = await CustomerRepository.get_customer_by_id_for_tenant(db, tenant_id, customer_id)
        if not customer:
            raise ResourceNotFoundException(f"Customer ID '{customer_id}' not found")

        kyc_record = await CustomerRepository.get_kyc_record(db, customer_id, tenant_id)
        kyc_documents = await CustomerRepository.get_kyc_documents(db, customer_id, tenant_id)

        enrollments = await EnrollmentRepository.get_enrollments_by_customer(db, tenant_id, customer_id)

        # Authoritative balance per enrollment. A customer holds a handful of
        # enrollments, and this is the only service allowed to state a scheme
        # balance — duplicating its derivation here to save queries is exactly
        # what this phase must not do.
        enrollment_rows: List[CustomerOverviewEnrollment] = []
        for enrollment in enrollments:
            balance = await SchemeBalanceService.get_balance(db, current_user, enrollment.id)
            enrollment_rows.append(
                CustomerOverviewEnrollment(
                    id=enrollment.id,
                    enrollment_number=balance.enrollment_number,
                    scheme_name=balance.scheme_name,
                    status=balance.status,
                    joined_date=str(balance.joined_date) if balance.joined_date else None,
                    maturity_date=str(balance.maturity_date) if balance.maturity_date else None,
                    total_paid=balance.total_paid,
                    total_redeemed=balance.total_redeemed,
                    available_balance=balance.available_balance,
                    can_redeem=balance.can_redeem,
                )
            )

        # Contributions across every enrollment in one query (joins through
        # SchemeEnrollment), not one query per enrollment.
        entries = await PassbookRepository.get_recent_entries_for_customer(
            db, tenant_id, customer_id, limit=OVERVIEW_ROW_CAP
        )
        contributions = [
            CustomerOverviewContribution(
                id=e.id,
                enrollment_id=e.enrollment_id,
                entry_number=e.entry_number,
                entry_date=e.entry_date,
                amount=e.amount,
                description=e.description,
            )
            for e in entries
        ]

        enrollment_numbers = {e.id: e.enrollment_number for e in enrollments}
        redemption_rows = await SchemeRedemptionRepository.list_for_customer(db, customer_id, tenant_id)
        redemptions = [
            CustomerOverviewRedemption(
                id=r.id,
                enrollment_id=r.enrollment_id,
                enrollment_number=enrollment_numbers.get(r.enrollment_id),
                invoice_number=r.invoice_number,
                amount=r.amount,
                redeemed_at=r.redeemed_at,
            )
            for r in redemption_rows
        ]

        sales = await SaleRepository.list_by_customer(db, tenant_id, customer_id, limit=OVERVIEW_ROW_CAP)
        sale_ids = [s.id for s in sales]
        invoice_by_sale = {s.id: s.invoice_number for s in sales}

        purchases = [
            CustomerOverviewPurchase(
                id=s.id,
                invoice_number=s.invoice_number,
                product_name=s.product_name,
                product_code=s.product_code,
                sale_timestamp=s.sale_timestamp,
                final_amount=s.final_amount,
                amount_paid=s.amount_paid or 0.0,
                amount_refunded=s.amount_refunded or 0.0,
                # Same definition the billing module uses everywhere else; a
                # reversed sale owes nothing.
                outstanding=(
                    0.0
                    if (s.sale_status or SALE_STATUS_COMPLETED) != SALE_STATUS_COMPLETED
                    else round(max(0.0, s.final_amount - (s.amount_paid or 0.0)), 2)
                ),
                payment_status=s.payment_status,
                sale_status=s.sale_status or SALE_STATUS_COMPLETED,
            )
            for s in sales
        ]

        # Both batched by sale id — no per-sale query.
        payment_rows = await SalePaymentRepository.list_by_sale_ids(db, sale_ids, tenant_id)
        payments = [
            CustomerOverviewPayment(
                id=p.id,
                sale_id=p.sale_id,
                invoice_number=invoice_by_sale.get(p.sale_id),
                amount=p.amount,
                payment_date=p.payment_date,
                payment_method=p.payment_method,
                source=p.source,
                reference_no=p.reference_no,
            )
            for p in payment_rows
        ]

        return_rows = await SaleReturnRepository.list_by_sale_ids(db, sale_ids, tenant_id)
        returns: List[CustomerOverviewReturn] = []
        for r in return_rows:
            # Scheme credit put back by this return — read from the redemption
            # ledger, the same source the enrollment screen shows.
            restored = await SchemeRedemptionRepository.sum_restorations_for_sale(db, r.sale_id, tenant_id)
            returns.append(
                CustomerOverviewReturn(
                    sale_id=r.sale_id,
                    invoice_number=r.invoice_number,
                    reason=r.reason,
                    refund_amount=r.refund_amount,
                    written_off_amount=r.outstanding_written_off,
                    scheme_restored=abs(restored),
                    inspection_outcome=r.inspection_status,
                    returned_at=r.returned_at,
                )
            )

        # Derived display type — never stored, so one customer record serves a
        # walk-in who later joins a scheme.
        if not enrollment_rows:
            customer_type = CUSTOMER_TYPE_WALK_IN
        elif purchases:
            customer_type = CUSTOMER_TYPE_HYBRID
        else:
            customer_type = CUSTOMER_TYPE_SCHEME

        totals = CustomerOverviewTotals(
            enrollment_count=len(enrollment_rows),
            scheme_total_paid=round(sum(e.total_paid for e in enrollment_rows), 2),
            scheme_total_redeemed=round(sum(e.total_redeemed for e in enrollment_rows), 2),
            scheme_available_balance=round(sum(e.available_balance for e in enrollment_rows), 2),
            purchase_count=len(purchases),
            purchase_total=round(sum(p.final_amount for p in purchases), 2),
            purchase_paid=round(sum(p.amount_paid for p in purchases), 2),
            purchase_outstanding=round(sum(p.outstanding for p in purchases), 2),
            return_count=len(returns),
            refund_total=round(sum(r.refund_amount for r in returns), 2),
        )

        return CustomerOverviewResponse(
            profile=CustomerOverviewProfile(
                id=customer.id,
                customer_code=customer.customer_code,
                name=customer.name,
                email=customer.email,
                phone=customer.phone,
                avatar_url=customer.avatar_url,
                is_active=customer.is_active,
                member_since=customer.member_since,
                created_at=customer.created_at,
                customer_type=customer_type,
            ),
            kyc=CustomerOverviewKyc(
                status=customer.kyc_status,
                doc_type=kyc_record.doc_type if kyc_record else None,
                record_status=kyc_record.status if kyc_record else None,
                verified_at=kyc_record.verified_at if kyc_record else None,
                rejection_reason=kyc_record.rejection_reason if kyc_record else None,
                document_count=len(kyc_documents),
            ),
            totals=totals,
            enrollments=enrollment_rows,
            contributions=contributions,
            redemptions=redemptions,
            purchases=purchases,
            payments=payments,
            returns=returns,
        )

    # ─── Phase 6C / Module 33: Vendor/Tenant Self-Service Profile ───

    @staticmethod
    async def get_tenant_profile(
        db: AsyncSession, current_user: User
    ) -> TenantProfileResponse:
        """Admin: read own tenant's profile/branding. Always
        current_user.tenant_id — no tenant_id is ever accepted as input."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        tenant = await CustomerRepository.get_tenant_by_id(db, current_user.tenant_id)
        if not tenant:
            raise ResourceNotFoundException("Tenant not found")
        return TenantProfileResponse.model_validate(tenant)

    @staticmethod
    async def update_tenant_profile(
        db: AsyncSession, current_user: User, req: TenantProfileUpdateRequest
    ) -> TenantProfileResponse:
        """Admin: update own tenant's contact/branding fields only — never
        name/slug/status, and never a different tenant (always
        current_user.tenant_id). contact_email/contact_phone/gst_number are
        DB-unique across tenants, so each is pre-checked for a conflict
        against a *different* tenant before writing, mirroring the same
        "read before write" uniqueness-check convention register_customer
        and superadmin_service's provisioning checks already established."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        tenant = await CustomerRepository.get_tenant_by_id(db, current_user.tenant_id)
        if not tenant:
            raise ResourceNotFoundException("Tenant not found")

        before_state = {
            "contact_email": tenant.contact_email,
            "contact_phone": tenant.contact_phone,
            "gst_number": tenant.gst_number,
            "brand_color": tenant.brand_color,
            "logo_url": tenant.logo_url,
        }

        if req.contact_email is not None and req.contact_email != tenant.contact_email:
            existing = await CustomerRepository.get_tenant_by_contact_email(db, req.contact_email)
            if existing and existing.id != tenant.id:
                raise ConflictException("This contact email is already in use by another store")
            tenant.contact_email = req.contact_email

        if req.contact_phone is not None and req.contact_phone != tenant.contact_phone:
            existing = await CustomerRepository.get_tenant_by_contact_phone(db, req.contact_phone)
            if existing and existing.id != tenant.id:
                raise ConflictException("This contact phone is already in use by another store")
            tenant.contact_phone = req.contact_phone

        if req.gst_number is not None and req.gst_number != tenant.gst_number:
            existing = await CustomerRepository.get_tenant_by_gst_number(db, req.gst_number)
            if existing and existing.id != tenant.id:
                raise ConflictException("This GST number is already in use by another store")
            tenant.gst_number = req.gst_number

        if req.brand_color is not None:
            tenant.brand_color = req.brand_color

        if req.logo_url is not None:
            tenant.logo_url = req.logo_url

        after_state = {
            "contact_email": tenant.contact_email,
            "contact_phone": tenant.contact_phone,
            "gst_number": tenant.gst_number,
            "brand_color": tenant.brand_color,
            "logo_url": tenant.logo_url,
        }

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="TENANT_PROFILE_UPDATE",
            target_entity="tenants",
            target_id=tenant.id,
            before_state=before_state,
            after_state=after_state,
        )

        await db.commit()
        await db.refresh(tenant)
        return TenantProfileResponse.model_validate(tenant)

    # ─── Phase 7 — Admin Branch Management ───

    @staticmethod
    async def get_branches_for_admin(
        db: AsyncSession, current_user: User
    ) -> List[BranchResponseItem]:
        """Admin: every branch for their own tenant, including inactive
        ones — distinct from get_branches, the active-only customer locator."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        branches = await CustomerRepository.get_all_tenant_branches(db, current_user.tenant_id)
        return [BranchResponseItem.model_validate(b) for b in branches]

    @staticmethod
    async def create_branch_for_admin(
        db: AsyncSession, current_user: User, req: BranchCreateRequest
    ) -> BranchResponseItem:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        branch_id = f"brn_{uuid.uuid4().hex[:12]}"
        branch = Branch(
            id=branch_id,
            tenant_id=current_user.tenant_id,
            name=req.name,
            address=req.address,
            phone=req.phone,
            latitude=req.latitude,
            longitude=req.longitude,
            is_active=True,
        )
        await CustomerRepository.create_branch(db, branch)

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="BRANCH_CREATE",
            target_entity="branches",
            target_id=branch_id,
            before_state=None,
            after_state={"name": req.name, "address": req.address},
        )

        await db.commit()
        await db.refresh(branch)
        return BranchResponseItem.model_validate(branch)

    @staticmethod
    async def update_branch_for_admin(
        db: AsyncSession, current_user: User, branch_id: str, req: BranchUpdateRequest
    ) -> BranchResponseItem:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        branch = await CustomerRepository.get_branch_by_id_for_tenant(db, current_user.tenant_id, branch_id)
        if not branch:
            raise ResourceNotFoundException(f"Branch ID '{branch_id}' not found")

        before_state = {"name": branch.name, "address": branch.address, "phone": branch.phone}

        if req.name is not None:
            branch.name = req.name
        if req.address is not None:
            branch.address = req.address
        if req.phone is not None:
            branch.phone = req.phone
        if req.latitude is not None:
            branch.latitude = req.latitude
        if req.longitude is not None:
            branch.longitude = req.longitude

        after_state = {"name": branch.name, "address": branch.address, "phone": branch.phone}

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="BRANCH_UPDATE",
            target_entity="branches",
            target_id=branch_id,
            before_state=before_state,
            after_state=after_state,
        )

        await db.commit()
        await db.refresh(branch)
        return BranchResponseItem.model_validate(branch)

    @staticmethod
    async def set_branch_status_for_admin(
        db: AsyncSession, current_user: User, branch_id: str, req: BranchStatusUpdateRequest
    ) -> BranchResponseItem:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        branch = await CustomerRepository.get_branch_by_id_for_tenant(db, current_user.tenant_id, branch_id)
        if not branch:
            raise ResourceNotFoundException(f"Branch ID '{branch_id}' not found")

        before_state = {"is_active": branch.is_active}
        branch.is_active = req.is_active
        after_state = {"is_active": branch.is_active}

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="BRANCH_ACTIVATE" if req.is_active else "BRANCH_DEACTIVATE",
            target_entity="branches",
            target_id=branch_id,
            before_state=before_state,
            after_state=after_state,
        )

        await db.commit()
        await db.refresh(branch)
        return BranchResponseItem.model_validate(branch)
        return TenantProfileResponse.model_validate(tenant)
