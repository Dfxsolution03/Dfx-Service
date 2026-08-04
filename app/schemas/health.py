from typing import Dict, Any, Optional
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    success: bool = True
    message: str = "DFX Solution Enterprise SaaS API is operational"
    data: Dict[str, Any] = Field(
        default_factory=lambda: {
            "environment": "development",
            "version": "1.0.0",
            "database": {"status": "healthy", "details": "connected"},
        }
    )
    meta: Dict[str, Any] = Field(default_factory=dict)
