from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class WishlistItemResponse(BaseModel):
    """Customer-facing — lean, no tenant_id, includes joined product info."""
    id: str
    product_id: str
    product_name: str
    product_price: Optional[float] = None
    product_image_path: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
