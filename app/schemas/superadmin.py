from datetime import datetime
from typing import List, Literal, Optional
from pydantic import BaseModel, EmailStr, Field, field_validator

# Reused directly — identical shape needed here as in the Reports module.
from app.schemas.report import DateRangeInfo

TenantStatus = Literal["Active", "Inactive"]
SubscriptionPlan = Literal["Starter", "Professional", "Business", "Enterprise"]


class SubscriptionSummary(BaseModel):
    id: str
    plan: str
    status: str
    trial_ends_at: Optional[datetime]

    class Config:
        from_attributes = True


class TenantListItem(BaseModel):
    id: str
    name: str
    slug: str
    status: str
    # Tenant has no owner/contact columns — derived from the tenant's first
    # Admin-role user, since that's the closest real relationship. Null if
    # the tenant has no Admin user yet.
    admin_name: Optional[str] = None
    admin_email: Optional[str] = None
    admin_phone: Optional[str] = None
    admin_is_active: Optional[bool] = None
    created_at: datetime

    class Config:
        from_attributes = True


class TenantDetailResponse(BaseModel):
    id: str
    name: str
    slug: str
    status: str
    admin_name: Optional[str] = None
    admin_email: Optional[str] = None
    admin_phone: Optional[str] = None
    # None when the tenant has no Admin user yet; otherwise the Admin
    # account's own is_active flag (see SuperAdminService.set_tenant_admin_status).
    admin_is_active: Optional[bool] = None
    # Module 29 — real columns now (previously Tenant had no branding fields
    # at all, see SESSION_HANDOFF.md §14/§17). None for every tenant
    # provisioned before this module, or provisioned without a custom color.
    brand_color: Optional[str] = None
    logo_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    # None only for tenants provisioned before subscriptions existed / seed
    # data with no Subscription row — see auth_service._enforce_tenant_access.
    subscription: Optional[SubscriptionSummary] = None

    class Config:
        from_attributes = True


class TenantSubscriptionUpdateRequest(BaseModel):
    """SuperAdmin: change plan and/or access mode for an existing tenant.
    access_mode='INDEFINITE' clears trial_ends_at entirely (no automatic
    expiry — the tenant only ever changes via SuperAdmin's own status
    toggle). access_mode='TRIAL' requires trial_days and (re)computes
    trial_ends_at from now, which also re-activates a previously-expired
    trial — this is the "extend access" action."""
    plan: Optional[str] = Field(None, min_length=2, max_length=50)
    access_mode: Literal["TRIAL", "INDEFINITE"]
    trial_days: Optional[int] = Field(None, ge=1, le=3650)

    @field_validator("trial_days")
    @classmethod
    def validate_trial_days(cls, v: Optional[int], info) -> Optional[int]:
        if info.data.get("access_mode") == "TRIAL" and not v:
            raise ValueError("trial_days is required when access_mode is TRIAL")
        return v


class TenantStatusUpdateRequest(BaseModel):
    status: TenantStatus


class TenantStatisticsResponse(BaseModel):
    """Composed from Module 12's ReportRepository, called against the target
    tenant_id rather than the current user's own tenant — see SuperAdminService."""
    tenant_id: str
    tenant_name: str
    range: DateRangeInfo
    total_customers: int
    active_enrollments: int
    completed_enrollments: int
    cancelled_enrollments: int
    total_revenue: float
    outstanding_dues: float
    total_gold_accumulated_grams: float
    active_schemes: int


class PlatformGrowthPoint(BaseModel):
    period_label: str
    new_tenants: int


class TenantStatusBreakdownItem(BaseModel):
    status: str
    count: int


class RecentTenantItem(BaseModel):
    id: str
    name: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class PlatformDashboardResponse(BaseModel):
    range: DateRangeInfo
    total_tenants: int
    active_tenants: int
    total_customers: int
    total_schemes: int
    total_enrollments: int
    total_payments: int
    total_payment_amount: float
    growth_trend: List[PlatformGrowthPoint]
    status_breakdown: List[TenantStatusBreakdownItem]
    recent_tenants: List[RecentTenantItem]


# ─── Module 29 — Tenant Provisioning ───


class TenantProvisionRequest(BaseModel):
    """One wizard submission = one atomic provisioning transaction (see
    SuperAdminService.provision_tenant). Field grouping mirrors the
    frontend wizard's steps 1:1 (Business Information / Admin Information /
    Subscription / Branding) purely for readability — validated as a single
    flat request, not as separate per-step calls."""

    # -- Business Information --------------------------------------------
    business_name: str = Field(..., min_length=2, max_length=100, example="Royal Gold & Diamonds")
    subdomain: str = Field(
        ...,
        min_length=2,
        max_length=100,
        pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$",
        description="Lowercase, hyphen-separated — becomes the tenant's unique slug.",
        example="royal-gold-diamonds",
    )
    business_address: str = Field(..., min_length=5, max_length=500, description="Used to seed the tenant's first Branch.")
    business_phone: str = Field(..., min_length=10, max_length=20, description="Used as both the tenant's contact phone and the default Branch's phone.")
    contact_email: Optional[EmailStr] = Field(None, description="Tenant's own business contact email — distinct from the Admin's login email.")
    gst_number: Optional[str] = Field(None, max_length=20)

    # -- Admin Information --------------------------------------------------
    admin_name: str = Field(..., min_length=2, max_length=100, example="Priya Sharma")
    admin_email: EmailStr = Field(..., description="Becomes the new Admin user's login email — must be globally unique.")
    admin_phone: Optional[str] = Field(None, min_length=10, max_length=15)

    # -- Subscription -----------------------------------------------------
    plan: SubscriptionPlan = "Professional"
    trial_days: int = Field(14, ge=0, le=365, description="Length of the default trial period.")

    # -- Branding -----------------------------------------------------------
    brand_color: Optional[str] = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$", description="Hex color, e.g. #2C6FBD. Defaults to the platform's own accent color if omitted.")


class BranchSummary(BaseModel):
    id: str
    name: str
    address: str
    phone: str

    class Config:
        from_attributes = True


class ProvisionedAdminSummary(BaseModel):
    id: str
    name: str
    email: Optional[str]
    phone: Optional[str]

    class Config:
        from_attributes = True


class TenantProvisionResponse(BaseModel):
    tenant: TenantDetailResponse
    branch: BranchSummary
    subscription: SubscriptionSummary
    admin: ProvisionedAdminSummary
    # Returned exactly once — never persisted in plaintext, never logged.
    # See SuperAdminService.provision_tenant's docstring for the full
    # security rationale.
    temporary_password: str
    activation_link: str
    activation_link_expires_at: datetime
    onboarding_email_sent: bool


class TenantAdminSummary(BaseModel):
    """The tenant's primary Admin account, with the account-level status a
    SuperAdmin can actually act on — distinct from ProvisionedAdminSummary,
    which is a one-time provisioning receipt with no status field."""
    id: str
    name: str
    email: Optional[str]
    phone: Optional[str]
    is_active: bool

    class Config:
        from_attributes = True


class TenantAdminStatusUpdateRequest(BaseModel):
    is_active: bool


class TenantAdminPasswordResetResponse(BaseModel):
    admin_email: str
    reset_email_sent: bool
