from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel


class AuditLogItem(BaseModel):
    id: str
    tenant_id: Optional[str] = None
    actor_user_id: str
    actor_name: str
    actor_role: str
    action: str
    target_entity: str
    target_id: Optional[str] = None
    before_state: Optional[str] = None
    after_state: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class PaginationInfo(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int


class AuditLogListResponse(BaseModel):
    logs: List[AuditLogItem]
    pagination: PaginationInfo
