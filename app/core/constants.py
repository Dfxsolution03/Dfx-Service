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
# Billing System — three INDEPENDENTLY grantable areas, each its own module
# key so Staff can be given e.g. New Sale without Inventory or Sales History.
STAFF_MODULE_BILLING_INVENTORY = "billing_inventory"
STAFF_MODULE_BILLING_NEW_SALE = "billing_new_sale"
STAFF_MODULE_BILLING_SALES_HISTORY = "billing_sales_history"

# Legacy umbrella. Retained ONLY for backward compatibility: existing Staff
# rows granted "billing" continue to receive all three areas (expanded at
# authorization time — see require_admin_or_staff_module). New assignments use
# the three granular keys above; "billing" is never handed out afresh.
STAFF_MODULE_BILLING = "billing"

# The granular areas a legacy "billing" grant expands to.
BILLING_UMBRELLA_CHILDREN = [
    STAFF_MODULE_BILLING_INVENTORY,
    STAFF_MODULE_BILLING_NEW_SALE,
    STAFF_MODULE_BILLING_SALES_HISTORY,
]

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
    STAFF_MODULE_BILLING_INVENTORY,
    STAFF_MODULE_BILLING_NEW_SALE,
    STAFF_MODULE_BILLING_SALES_HISTORY,
    STAFF_MODULE_BILLING,
]

# Phase 8 — Staff permission GROUPING for the Admin UI's two dropdowns
# (Scheme / Business). This is a PRESENTATION + validation grouping over the
# EXISTING STAFF_MODULE_* keys above — it introduces no new permission keys,
# renames nothing, and does not change how require_admin_or_staff_module()
# authorizes. A staff account is still granted a flat set of these same module
# keys (User.staff_permissions); the groups only tell the frontend how to lay
# them out and give each key a context label.
#
# Notes on the mapping to existing keys (no new keys invented):
#   * "reports", "analytics", "notifications" are single shared modules — they
#     appear under BOTH groups with a context label (e.g. "Scheme Reports" vs
#     "Business Reports"); granting the key from either dropdown grants the one
#     underlying permission.
#   * Billing is three INDEPENDENT keys — billing_inventory / billing_new_sale
#     / billing_sales_history — each grantable on its own. The legacy "billing"
#     umbrella is not offered in the UI; it survives only for existing grants.
#   * Passbook access is covered by the "payments" key (no separate key exists).
#   * "support" is a valid module but is not part of either business dropdown.
STAFF_MODULE_GROUP_SCHEME = "SCHEME"
STAFF_MODULE_GROUP_BUSINESS = "BUSINESS"

STAFF_MODULE_GROUPS = [
    {
        "group": STAFF_MODULE_GROUP_SCHEME,
        "label": "Scheme",
        "modules": [
            {"key": STAFF_MODULE_SCHEMES, "label": "Schemes"},
            {"key": STAFF_MODULE_ENROLLMENTS, "label": "Enrollments"},
            {"key": STAFF_MODULE_REPORTS, "label": "Scheme Reports"},
            {"key": STAFF_MODULE_ANALYTICS, "label": "Scheme Analytics"},
            {"key": STAFF_MODULE_NOTIFICATIONS, "label": "Scheme Notifications"},
        ],
    },
    {
        "group": STAFF_MODULE_GROUP_BUSINESS,
        "label": "Business",
        "modules": [
            {"key": STAFF_MODULE_CUSTOMERS, "label": "Customers"},
            {"key": STAFF_MODULE_KYC, "label": "KYC"},
            {"key": STAFF_MODULE_BILLING_INVENTORY, "label": "Inventory"},
            {"key": STAFF_MODULE_BILLING_NEW_SALE, "label": "New Sale"},
            {"key": STAFF_MODULE_BILLING_SALES_HISTORY, "label": "Sales History"},
            # Passbook has no staff permission key and remains Admin-only; this
            # key grants Payments access only.
            {"key": STAFF_MODULE_PAYMENTS, "label": "Payments"},
            {"key": STAFF_MODULE_CATALOGUE, "label": "Catalogue"},
            {"key": STAFF_MODULE_MARKETING, "label": "Marketing"},
            {"key": STAFF_MODULE_GOLD_RATE, "label": "Gold Rate"},
            {"key": STAFF_MODULE_BRANCHES, "label": "Branches"},
            {"key": STAFF_MODULE_REPORTS, "label": "Business Reports"},
            {"key": STAFF_MODULE_ANALYTICS, "label": "Business Analytics"},
            {"key": STAFF_MODULE_NOTIFICATIONS, "label": "Business Notifications"},
        ],
    },
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
# A returned item never re-enters sellable stock automatically: the return puts
# it in RETURNED_PENDING_INSPECTION, and only an explicit Admin inspection
# decision moves it to IN_STOCK (resalable) or DAMAGED (permanently unsellable).
# SaleService._get_sellable_item_and_rate only ever sells IN_STOCK, so both of
# these are non-sellable by construction.
STOCK_STATUS_RETURNED_PENDING_INSPECTION = "RETURNED_PENDING_INSPECTION"
STOCK_STATUS_DAMAGED = "DAMAGED"
INVENTORY_STOCK_STATUSES = [
    STOCK_STATUS_IN_STOCK,
    STOCK_STATUS_SOLD,
    STOCK_STATUS_INACTIVE,
    STOCK_STATUS_RETURNED_PENDING_INSPECTION,
    STOCK_STATUS_DAMAGED,
]

# Sale.sale_status — the SALE lifecycle, deliberately separate from
# Sale.payment_status (the money lifecycle). One sale carries exactly one
# inventory item in this data model, so a sale is either wholly intact or
# wholly reversed; there is no PARTIALLY_RETURNED state, because the schema
# cannot represent one item of a multi-item invoice coming back.
SALE_STATUS_COMPLETED = "COMPLETED"
SALE_STATUS_RETURNED = "RETURNED"
SALE_STATUS_CANCELLED = "CANCELLED"
SALE_STATUSES = [SALE_STATUS_COMPLETED, SALE_STATUS_RETURNED, SALE_STATUS_CANCELLED]

# Sale.payment_status — money only. PENDING/PARTIAL/PAID are derived from the
# collection ledger; REFUNDED/PARTIALLY_REFUNDED are reached only through a
# return, and are derived from refunded-vs-collected on the same ledger.
PAYMENT_STATUS_PENDING = "PENDING"
PAYMENT_STATUS_PARTIAL = "PARTIAL"
PAYMENT_STATUS_PAID = "PAID"
PAYMENT_STATUS_REFUNDED = "REFUNDED"
PAYMENT_STATUS_PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
SALE_PAYMENT_STATUSES = [
    PAYMENT_STATUS_PENDING, PAYMENT_STATUS_PARTIAL, PAYMENT_STATUS_PAID,
    PAYMENT_STATUS_REFUNDED, PAYMENT_STATUS_PARTIALLY_REFUNDED,
]

# SaleReturn.return_type — why the sale was reversed. Mechanically identical
# (item comes back, money is refunded, outstanding is written off); kept as
# distinct labels because the Admin's books and the customer conversation
# distinguish "cancelled before it left the counter" from "brought back after
# delivery".
RETURN_TYPE_RETURN = "RETURN"
RETURN_TYPE_CANCELLATION = "CANCELLATION"
SALE_RETURN_TYPES = [RETURN_TYPE_RETURN, RETURN_TYPE_CANCELLATION]

# SaleReturn.inspection_status — outcome of the post-return physical check.
INSPECTION_PENDING = "PENDING"
INSPECTION_RESALABLE = "RESALABLE"
INSPECTION_DAMAGED = "DAMAGED"
SALE_RETURN_INSPECTION_STATUSES = [INSPECTION_PENDING, INSPECTION_RESALABLE, INSPECTION_DAMAGED]

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
