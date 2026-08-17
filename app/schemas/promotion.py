from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field

BannerType = Literal["STANDARD", "IMAGE_ONLY"]


class PromotionCreateRequest(BaseModel):
    # Optional + defaulted so existing STANDARD callers (which never sent it)
    # remain compatible. title is optional here because IMAGE_ONLY needs none;
    # the service enforces title-for-STANDARD and image-for-IMAGE_ONLY.
    banner_type: BannerType = "STANDARD"
    title: Optional[str] = Field(None, max_length=200)
    subtitle: Optional[str] = Field(None, max_length=300)
    description: Optional[str] = Field(None, max_length=2000)
    image_url: Optional[str] = Field(None, max_length=500)
    button_text: Optional[str] = Field(None, max_length=50)
    button_link: Optional[str] = Field(None, max_length=500)
    background_color: Optional[str] = Field(None, max_length=20)
    text_color: Optional[str] = Field(None, max_length=20)
    priority: int = 0
    is_active: bool = True
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


class PromotionUpdateRequest(BaseModel):
    banner_type: Optional[BannerType] = None
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    subtitle: Optional[str] = Field(None, max_length=300)
    description: Optional[str] = Field(None, max_length=2000)
    image_url: Optional[str] = Field(None, max_length=500)
    button_text: Optional[str] = Field(None, max_length=50)
    button_link: Optional[str] = Field(None, max_length=500)
    background_color: Optional[str] = Field(None, max_length=20)
    text_color: Optional[str] = Field(None, max_length=20)
    priority: Optional[int] = None
    is_active: Optional[bool] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


class PromotionResponse(BaseModel):
    """Admin-facing — full record."""
    id: str
    tenant_id: str
    banner_type: str = "STANDARD"
    title: str
    subtitle: Optional[str]
    description: Optional[str]
    image_url: Optional[str]
    button_text: Optional[str]
    button_link: Optional[str]
    background_color: Optional[str]
    text_color: Optional[str]
    priority: int
    is_active: bool
    start_date: Optional[datetime]
    end_date: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CustomerBannerResponse(BaseModel):
    """Customer-facing — lean, includes derived store branding so the app
    doesn't need a second call to render the banner."""
    id: str
    banner_type: str = "STANDARD"
    title: str
    subtitle: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    button_text: Optional[str] = None
    button_link: Optional[str] = None
    background_color: Optional[str] = None
    text_color: Optional[str] = None
    store_name: Optional[str] = None
    store_logo_url: Optional[str] = None

    class Config:
        from_attributes = True
