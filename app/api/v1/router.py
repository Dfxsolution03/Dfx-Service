from fastapi import APIRouter
from app.api.v1.endpoints import (
    health, auth, customer, goldrate, scheme, enrollment, passbook, payment,
    report, audit, superadmin, catalogue, support, customer_catalogue, wishlist,
    dashboard, staff, notification,
)

api_router = APIRouter()

# Include health endpoint
api_router.include_router(health.router, tags=["Health"])

# Include auth & user endpoints
api_router.include_router(auth.router, tags=["Authentication & Users"])

# Include customer endpoints
api_router.include_router(customer.router, tags=["Customer Module"])

# Include gold rate endpoints
api_router.include_router(goldrate.router, tags=["Gold Rate Module"])

# Include scheme endpoints
api_router.include_router(scheme.router, tags=["Scheme Module"])

# Include enrollment endpoints
api_router.include_router(enrollment.router, tags=["Enrollment Module"])

# Include passbook endpoints
api_router.include_router(passbook.router, tags=["Passbook Module"])

# Include payment endpoints
api_router.include_router(payment.router, tags=["Payment Module"])

# Include reports endpoints
api_router.include_router(report.router, tags=["Reports Module"])

# Include audit log read endpoints
api_router.include_router(audit.router, tags=["Audit Log Module"])

# Include superadmin platform/tenant endpoints
api_router.include_router(superadmin.router, tags=["SuperAdmin Platform Module"])

# Include catalogue studio endpoints (Module 20)
api_router.include_router(catalogue.router, tags=["Catalogue Studio Module"])

# Phase 6A / Module 31 — Customer Support System
api_router.include_router(support.router, tags=["Support Module"])

# Phase 6A / Module 31 — Customer-facing Catalogue (read-only)
api_router.include_router(customer_catalogue.router, tags=["Customer Catalogue Module"])

# Phase 6A / Module 31 — Wishlist
api_router.include_router(wishlist.router, tags=["Wishlist Module"])

# Notification Module
api_router.include_router(notification.router, tags=["Notification Module"])

# Phase 6B / Module 32 — Customer Dashboard
api_router.include_router(dashboard.router, tags=["Dashboard Module"])

# Phase 6C / Module 33 — Admin Staff Management
api_router.include_router(staff.router, tags=["Staff Module"])
