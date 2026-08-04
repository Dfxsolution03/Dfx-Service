from typing import Literal
from pydantic import BaseModel

ExportFormat = Literal["csv", "excel", "markdown"]


class ExportFileResponse(BaseModel):
    """Generic downloadable-file envelope, returned by every export endpoint
    across every module. Content travels as base64 inside the standard
    response envelope (not a raw binary/streaming response) so every export
    endpoint reuses the app's existing auth/error-handling conventions on
    both the backend and frontend, instead of needing a separate download
    code path."""
    filename: str
    content_type: str
    format: ExportFormat
    content_base64: str
    row_count: int
