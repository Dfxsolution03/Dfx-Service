from typing import List
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.models.enrollment import STATUS_ACTIVE
from app.models.payment import STATUS_SUCCESS as PAYMENT_SUCCESS, STATUS_PENDING as PAYMENT_PENDING
from app.models.support import STATUS_OPEN, STATUS_IN_PROGRESS
from app.repositories.customer_repository import CustomerRepository
from app.repositories.enrollment_repository import EnrollmentRepository
from app.repositories.payment_repository import PaymentRepository
from app.repositories.passbook_repository import PassbookRepository
from app.repositories.wishlist_repository import WishlistRepository
from app.repositories.support_repository import SupportRepository
from app.repositories.notification_repository import NotificationRepository
from app.repositories.customer_catalogue_repository import CustomerCatalogueRepository
from app.services.goldrate_service import GoldRateService
from app.exceptions.base import ForbiddenException
from app.schemas.dashboard import (
    DashboardResponse,
    DashboardProfileSummary,
    DashboardGoldRateSummary,
    DashboardSchemeSummary,
    DashboardPassbookSummary,
    DashboardPassbookEntryItem,
    DashboardPaymentSummary,
    DashboardPaymentItem,
    DashboardSupportSummary,
    DashboardNotificationSummary,
)
from app.schemas.customer_catalogue import CustomerProductListItem

FEATURED_PRODUCTS_LIMIT = 6
RECENT_PASSBOOK_LIMIT = 5
RECENT_PAYMENTS_LIMIT = 5

# Same open-ticket definition as MyTicketsScreen's "active" filter would use —
# a ticket is still "open" from the customer's point of view until it's
# RESOLVED or CLOSED.
OPEN_TICKET_STATUSES = {STATUS_OPEN, STATUS_IN_PROGRESS}


def _to_product_list_item(product) -> CustomerProductListItem:
    """Same primary-image resolution as customer_catalogue_service.py's
    _to_list_item/_primary_image_path — duplicated rather than importing a
    private (underscore-prefixed) cross-module helper."""
    primary_image = None
    for img in product.images:
        if img.is_primary:
            primary_image = img.storage_path
            break
    if not primary_image and product.images:
        primary_image = product.images[0].storage_path

    return CustomerProductListItem(
        id=product.id,
        name=product.name,
        description=product.description,
        category=product.category,
        purity=product.purity,
        price=product.price,
        weight_grams=product.weight_grams,
        primary_image_path=primary_image,
    )


def _profile_completion_percent(current_user: User, has_address: bool) -> int:
    """
    No "profile completion" concept exists anywhere else in this codebase —
    this is a fresh, pure computation over already-fetched fields, not a
    stored value. Five equally-weighted checks, 20% each: email, phone,
    avatar, KYC verified, at least one saved address.
    """
    checks = [
        bool(current_user.email),
        bool(current_user.phone),
        bool(current_user.avatar_url),
        current_user.kyc_status == "Verified",
        has_address,
    ]
    return round(100 * sum(checks) / len(checks))


class DashboardService:
    @staticmethod
    async def get_dashboard(db: AsyncSession, current_user: User) -> DashboardResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        tenant_id = current_user.tenant_id
        customer_id = current_user.id

        # -- Profile ----------------------------------------------------
        addresses = await CustomerRepository.get_user_addresses(db, customer_id, tenant_id)
        profile = DashboardProfileSummary(
            name=current_user.name,
            avatar_url=current_user.avatar_url,
            kyc_status=current_user.kyc_status,
            profile_completion_percent=_profile_completion_percent(current_user, bool(addresses)),
            member_since=current_user.member_since,
        )

        # -- Gold rate ----------------------------------------------------
        # Reuses GoldRateService (not GoldRateRepository directly) so the IST
        # "today" resolution stays in exactly one place, per established
        # convention (see goldrate_service.py's IST fixed-offset helper).
        rate = await GoldRateService.get_customer_today_rate(db, current_user)
        gold_rate = (
            DashboardGoldRateSummary(
                rate_24k=rate.rate_24k,
                effective_date=rate.effective_date,
                silver_999=rate.silver_999,
            )
            if rate else None
        )

        # -- Schemes / enrollments -----------------------------------------
        enrollments = await EnrollmentRepository.get_enrollments_by_customer(db, tenant_id, customer_id)
        active_enrollment_count = sum(1 for e in enrollments if e.status == STATUS_ACTIVE)

        # -- Payments -------------------------------------------------------
        payments = await PaymentRepository.get_payments_by_customer(db, tenant_id, customer_id)
        total_invested = sum(p.amount for p in payments if p.payment_status == PAYMENT_SUCCESS)
        pending_count = sum(1 for p in payments if p.payment_status == PAYMENT_PENDING)
        recent_payments: List[DashboardPaymentItem] = [
            DashboardPaymentItem(
                id=p.id,
                scheme_name=p.enrollment.scheme.name,
                amount=p.amount,
                payment_date=p.payment_date,
                payment_method=p.payment_method,
                payment_status=p.payment_status,
            )
            for p in payments[:RECENT_PAYMENTS_LIMIT]
        ]

        # -- Passbook ---------------------------------------------------------
        # Lifetime-accurate total via a SUM()/COUNT() query (not derived from
        # the bounded "recent" list below) — per explicit instruction.
        gold_totals = await PassbookRepository.get_gold_totals_for_customer(db, tenant_id, customer_id)
        recent_entries = await PassbookRepository.get_recent_entries_for_customer(
            db, tenant_id, customer_id, limit=RECENT_PASSBOOK_LIMIT
        )
        passbook = DashboardPassbookSummary(
            recent_entries=[DashboardPassbookEntryItem.model_validate(e) for e in recent_entries]
        )
        schemes = DashboardSchemeSummary(
            active_enrollment_count=active_enrollment_count,
            total_invested=total_invested,
            total_gold_accumulated_grams=gold_totals["total_gold_weight"],
        )

        # -- Wishlist -------------------------------------------------------
        wishlist_items = await WishlistRepository.get_items_by_user(db, customer_id, tenant_id)
        wishlist_count = len(wishlist_items)

        # -- Support ----------------------------------------------------------
        tickets = await SupportRepository.get_tickets_by_user(db, customer_id, tenant_id)
        open_ticket_count = sum(1 for t in tickets if t.status in OPEN_TICKET_STATUSES)

        # -- Notifications ------------------------------------------------------
        unread_notification_count = await NotificationRepository.get_unread_count(db, customer_id, tenant_id)

        # -- Featured products (proxy: newest active products) ----------------
        # Product has no is_featured flag and the admin catalogue module is
        # explicitly out of scope to modify — this is an honest proxy, not a
        # curated "featured" set. Reuses the existing Phase 6A read-only
        # customer catalogue repository as-is.
        featured_products, _total = await CustomerCatalogueRepository.list_products(
            db, tenant_id, page=1, limit=FEATURED_PRODUCTS_LIMIT, search=None, category=None, sort="newest"
        )

        return DashboardResponse(
            profile=profile,
            gold_rate=gold_rate,
            schemes=schemes,
            passbook=passbook,
            payments=DashboardPaymentSummary(recent_payments=recent_payments, pending_count=pending_count),
            wishlist_count=wishlist_count,
            support=DashboardSupportSummary(open_ticket_count=open_ticket_count),
            notifications=DashboardNotificationSummary(unread_count=unread_notification_count),
            featured_products=[_to_product_list_item(p) for p in featured_products],
        )
