import base64
import csv
import io
from dataclasses import dataclass
from typing import Any, Sequence

from openpyxl import Workbook

from app.schemas.export import ExportFileResponse, ExportFormat

CONTENT_TYPES: dict[ExportFormat, str] = {
    "csv": "text/csv",
    "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "markdown": "text/markdown",
}

EXTENSIONS: dict[ExportFormat, str] = {"csv": "csv", "excel": "xlsx", "markdown": "md"}


@dataclass(frozen=True)
class ExportColumn:
    """One column of a tabular export. `key` looks up each row dict; `label`
    is the human-readable header shown in the generated file."""
    key: str
    label: str


class ExportService:
    """The single place tabular data becomes a downloadable file, for any
    module. Every export endpoint across the codebase should shape its data
    into (columns, rows) — plain dicts and column definitions, already
    formatted as display strings/numbers — and call generate() here. No
    module should implement its own CSV/Excel/Markdown serialization; that
    would be exactly the duplicated export logic this service exists to
    avoid. Domain-agnostic on purpose: it has no knowledge of reports,
    tenants, or audit logs, only of rows and columns."""

    @staticmethod
    def generate(
        rows: Sequence[dict[str, Any]],
        columns: Sequence[ExportColumn],
        fmt: ExportFormat,
        filename_stem: str,
    ) -> ExportFileResponse:
        if fmt == "csv":
            raw = ExportService._to_csv(rows, columns)
        elif fmt == "excel":
            raw = ExportService._to_excel(rows, columns)
        elif fmt == "markdown":
            raw = ExportService._to_markdown(rows, columns)
        else:
            raise ValueError(f"Unsupported export format: {fmt}")

        return ExportFileResponse(
            filename=f"{filename_stem}.{EXTENSIONS[fmt]}",
            content_type=CONTENT_TYPES[fmt],
            format=fmt,
            content_base64=base64.b64encode(raw).decode("ascii"),
            row_count=len(rows),
        )

    @staticmethod
    def _to_csv(rows: Sequence[dict[str, Any]], columns: Sequence[ExportColumn]) -> bytes:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([c.label for c in columns])
        for row in rows:
            writer.writerow([row.get(c.key, "") for c in columns])
        # utf-8-sig (BOM) so Excel opens the CSV with correct encoding on Windows.
        return buf.getvalue().encode("utf-8-sig")

    @staticmethod
    def _to_excel(rows: Sequence[dict[str, Any]], columns: Sequence[ExportColumn]) -> bytes:
        wb = Workbook()
        ws = wb.active
        ws.append([c.label for c in columns])
        for row in rows:
            ws.append([row.get(c.key, "") for c in columns])
        for i, column in enumerate(ws.columns, start=1):
            longest = max((len(str(cell.value)) for cell in column if cell.value is not None), default=10)
            ws.column_dimensions[column[0].column_letter].width = min(longest + 2, 60)
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    @staticmethod
    def _to_markdown(rows: Sequence[dict[str, Any]], columns: Sequence[ExportColumn]) -> bytes:
        headers = [c.label for c in columns]
        lines = [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
        ]
        for row in rows:
            cells = [str(row.get(c.key, "")).replace("|", "\\|") for c in columns]
            lines.append("| " + " | ".join(cells) + " |")
        return ("\n".join(lines) + "\n").encode("utf-8")
