# Role Name Constants
ROLE_CUSTOMER = "Customer"
ROLE_STAFF = "Staff"
ROLE_ADMIN = "Admin"
ROLE_SUPERADMIN = "SuperAdmin"

# Permission Constants
PERM_SCHEMES_READ = "schemes:read"
PERM_SCHEMES_MANAGE = "schemes:manage"
PERM_PAYMENTS_PAY = "payments:pay"
PERM_PAYMENTS_MANUAL = "payments:manual"
PERM_PASSBOOK_READ = "passbook:read"
PERM_CATALOGUE_READ = "catalogue:read"
PERM_CATALOGUE_MANAGE = "catalogue:manage"
PERM_ORDERS_CREATE = "orders:create"
PERM_ORDERS_READ = "orders:read"
PERM_CUSTOMERS_MANAGE = "customers:manage"
PERM_TENANTS_MANAGE = "tenants:manage"
PERM_BRANDING_MANAGE = "branding:manage"

# Permission Mappings by Role
ROLE_PERMISSIONS_MAP = {
    ROLE_CUSTOMER: [
        PERM_SCHEMES_READ,
        PERM_PAYMENTS_PAY,
        PERM_PASSBOOK_READ,
        PERM_CATALOGUE_READ,
        PERM_ORDERS_CREATE,
        PERM_ORDERS_READ,
    ],
    ROLE_STAFF: [
        PERM_SCHEMES_READ,
        PERM_PAYMENTS_MANUAL,
        PERM_PASSBOOK_READ,
        PERM_CATALOGUE_READ,
        PERM_ORDERS_READ,
    ],
    ROLE_ADMIN: [
        PERM_SCHEMES_READ,
        PERM_SCHEMES_MANAGE,
        PERM_PAYMENTS_MANUAL,
        PERM_PASSBOOK_READ,
        PERM_CATALOGUE_READ,
        PERM_CATALOGUE_MANAGE,
        PERM_ORDERS_READ,
        PERM_CUSTOMERS_MANAGE,
    ],
    ROLE_SUPERADMIN: [
        PERM_SCHEMES_READ,
        PERM_SCHEMES_MANAGE,
        PERM_PAYMENTS_PAY,
        PERM_PAYMENTS_MANUAL,
        PERM_PASSBOOK_READ,
        PERM_CATALOGUE_READ,
        PERM_CATALOGUE_MANAGE,
        PERM_ORDERS_CREATE,
        PERM_ORDERS_READ,
        PERM_CUSTOMERS_MANAGE,
        PERM_TENANTS_MANAGE,
        PERM_BRANDING_MANAGE,
    ],
}

# Staff module access grants (Phase — Admin/Staff granular permissions).
# Distinct from ROLE_PERMISSIONS_MAP above: that map is fixed per-role and
# unused by any live endpoint today. This is per-INDIVIDUAL-STAFF-USER —
# each Staff account is granted its own subset of these module keys
# (User.staff_permissions), so two Staff accounts under the same tenant can
# have entirely different access. Admin/SuperAdmin are never gated by this;
# they always have unrestricted tenant access.
STAFF_MODULE_CUSTOMERS = "customers"
STAFF_MODULE_KYC = "kyc"
STAFF_MODULE_GOLD_RATE = "gold_rate"
STAFF_MODULE_SCHEMES = "schemes"
STAFF_MODULE_ENROLLMENTS = "enrollments"
STAFF_MODULE_PAYMENTS = "payments"
STAFF_MODULE_CATALOGUE = "catalogue"
STAFF_MODULE_MARKETING = "marketing"
STAFF_MODULE_REPORTS = "reports"
STAFF_MODULE_ANALYTICS = "analytics"
STAFF_MODULE_BRANCHES = "branches"
STAFF_MODULE_SUPPORT = "support"
STAFF_MODULE_NOTIFICATIONS = "notifications"
# Billing System (Inventory + Selling/Sales History) — one module key gates
# all three sub-screens, same "one module key, several sub-features" grant
# granularity as STAFF_MODULE_CATALOGUE (images/designs/rendering all live
# under "catalogue").
STAFF_MODULE_BILLING = "billing"

ALL_STAFF_MODULES = [
    STAFF_MODULE_CUSTOMERS,
    STAFF_MODULE_KYC,
    STAFF_MODULE_GOLD_RATE,
    STAFF_MODULE_SCHEMES,
    STAFF_MODULE_ENROLLMENTS,
    STAFF_MODULE_PAYMENTS,
    STAFF_MODULE_CATALOGUE,
    STAFF_MODULE_MARKETING,
    STAFF_MODULE_REPORTS,
    STAFF_MODULE_ANALYTICS,
    STAFF_MODULE_BRANCHES,
    STAFF_MODULE_SUPPORT,
    STAFF_MODULE_NOTIFICATIONS,
    STAFF_MODULE_BILLING,
]

# Billing Module — Inventory / Selling. Karat-to-24K fraction table
# (karat/24), the standard jewellery-industry purity conversion — GoldRate
# and MarketRate only ever store a 24K rate, so a purity-specific rate is
# always derived from it via this real, well-known ratio (e.g. 22K = 916
# hallmark = 22/24), never a fabricated/independent rate.
PURITY_KARATS = {
    "9K": 9,
    "14K": 14,
    "18K": 18,
    "20K": 20,
    "22K": 22,
    "24K": 24,
}
PURITY_CHOICES = list(PURITY_KARATS.keys())

# Making Charge / Wastage configurable calculation types.
CHARGE_TYPE_FIXED = "FIXED"
CHARGE_TYPE_PER_GRAM = "PER_GRAM"
CHARGE_TYPE_PERCENTAGE = "PERCENTAGE"
CHARGE_CALCULATION_TYPES = [CHARGE_TYPE_FIXED, CHARGE_TYPE_PER_GRAM, CHARGE_TYPE_PERCENTAGE]

# InventoryItem.stock_status values.
STOCK_STATUS_IN_STOCK = "IN_STOCK"
STOCK_STATUS_SOLD = "SOLD"
STOCK_STATUS_INACTIVE = "INACTIVE"
INVENTORY_STOCK_STATUSES = [STOCK_STATUS_IN_STOCK, STOCK_STATUS_SOLD, STOCK_STATUS_INACTIVE]

# Pricing mode — a label only. AUTO: system-calculated final amount (no
# customer_price given). HYBRID: system shows a suggested price, admin may
# override via customer_price. MANUAL: admin always supplies customer_price.
# Purely informational for the UI; BillingCalculationEngine's behavior is
# already determined by whether customer_price is present, not by this
# label — see app/services/billing_service.py.
PRICING_MODE_AUTO = "AUTO"
PRICING_MODE_HYBRID = "HYBRID"
PRICING_MODE_MANUAL = "MANUAL"
PRICING_MODES = [PRICING_MODE_AUTO, PRICING_MODE_HYBRID, PRICING_MODE_MANUAL]

# Default-resolution sources, for UI feedback only (see BillingDefaultsService).
DEFAULT_SOURCE_VENDOR = "VENDOR"
DEFAULT_SOURCE_CATEGORY = "CATEGORY"
DEFAULT_SOURCE_STORE = "STORE"
DEFAULT_SOURCE_NONE = "NONE"

# Notification campaign constants
NOTIFICATION_CHANNELS = ["IN_APP", "EMAIL", "WHATSAPP", "SMS", "PUSH"]
NOTIFICATION_TARGET_TYPES = ["ALL", "CUSTOMERS", "SCHEME"]
NOTIFICATION_STATUSES = ["DRAFT", "SENT", "FAILED", "CANCELLED"]

# Integration provider registry keys
INTEGRATION_PROVIDERS = ["gold_rate", "email", "whatsapp", "sms", "payment_gateway"]
