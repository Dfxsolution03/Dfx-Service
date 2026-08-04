from contextvars import ContextVar
from typing import Optional

_tenant_id_context_var: ContextVar[Optional[str]] = ContextVar("tenant_id", default=None)


def set_current_tenant_id(tenant_id: Optional[str]) -> None:
    """Set tenant_id for the current async execution context."""
    _tenant_id_context_var.set(tenant_id)


def get_current_tenant_id() -> Optional[str]:
    """Get tenant_id from the current async execution context."""
    return _tenant_id_context_var.get()
