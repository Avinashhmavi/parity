from __future__ import annotations

from ..config import Settings
from .base import BoardBackend, Table
from .xlsx import XlsxBackend

__all__ = ["BoardBackend", "Table", "XlsxBackend", "make_backend"]


def make_backend(settings: Settings) -> BoardBackend:
    if settings.backend == "gsheets":
        from .gsheets import GoogleSheetsBackend

        return GoogleSheetsBackend(settings.google_sheet_id, settings.google_credentials)
    return XlsxBackend(settings.xlsx_path)
