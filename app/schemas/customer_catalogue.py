from typing import List, Literal, Optional
from pydantic import BaseModel

SortOption = Literal["newest", "price_asc", "price_desc", "name_asc"]


class CustomerProductImageResponse(BaseModel):
    id: str
    storage_path: str
    variant_type: str
    is_primary: bool

    class Config:
        from_attributes = True


class CustomerProductListItem(BaseModel):
    """Lean, customer-facing — no tenant_id/created_by/internal variant
    bookkeeping, matching rule #4's "customer responses are lean" convention."""
    id: str
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    purity: Optional[str] = None
    price: Optional[float] = None
    weight_grams: Optional[float] = None
    primary_image_path: Optional[str] = None

    class Config:
        from_attributes = True


class CustomerProductDetailResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    sku: Optional[str] = None
    purity: Optional[str] = None
    price: Optional[float] = None
    weight_grams: Optional[float] = None
    tags: List[str] = []
    images: List[CustomerProductImageResponse] = []

    class Config:
        from_attributes = True


class ProductListPaginationInfo(BaseModel):
    """Mirrors the shape of audit.py's PaginationInfo for consistency
    across this codebase's list endpoints."""
    page: int
    page_size: int
    total_items: int
    total_pages: int
