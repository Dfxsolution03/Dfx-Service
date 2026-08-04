from fastapi import APIRouter
from app.api.v1.endpoints import health, auth, customer, goldrate, scheme, enrollment, passbook, payment, report, audit, superadmin, catalogue

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
