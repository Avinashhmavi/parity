"""Google Sheets backend (gspread + a service account).

Same contract as the Excel backend. Setup: create a service account, share the
spreadsheet with its email as an editor, then set ``BOARD_BACKEND=gsheets``,
``GOOGLE_SHEET_ID`` and ``GOOGLE_SERVICE_ACCOUNT`` (path to the JSON key, or
the JSON itself).

Not exercised against live Google in this repository's tests (no credentials
in CI); the logic around it is shared with the Excel backend and tested there.
"""

from __future__ import annotations

import json
from typing import Dict, List, Sequence, Tuple

from .. import board
from .base import BoardBackend, Table


class GoogleSheetsBackend(BoardBackend):
    name = "gsheets"

    def __init__(self, sheet_id: str, credentials: str):
        if not sheet_id:
            raise ValueError("GOOGLE_SHEET_ID is required for BOARD_BACKEND=gsheets")
        if not credentials:
            raise ValueError("GOOGLE_SERVICE_ACCOUNT is required for BOARD_BACKEND=gsheets")
        import gspread  # imported lazily so Excel-only installs do not need it

        self._gspread = gspread
        if credentials.lstrip().startswith("{"):
            client = gspread.service_account_from_dict(json.loads(credentials))
        else:
            client = gspread.service_account(filename=credentials)
        self._book = client.open_by_key(sheet_id)
        self._sheet_id = sheet_id

    def describe(self) -> str:
        return f"gsheets:{self._sheet_id}"

    def _worksheet(self, name: str):
        try:
            return self._book.worksheet(name)
        except self._gspread.WorksheetNotFound:
            return None

    def read_table(self, name: str) -> List[Dict[str, str]]:
        ws = self._worksheet(name)
        if ws is None:
            return []
        values = ws.get_all_values()
        if not values:
            return []
        headers = [h.strip() for h in values[0]]
        out = []
        for row in values[1:]:
            record = {h: (row[i] if i < len(row) else "") for i, h in enumerate(headers) if h}
            if any(v.strip() for v in record.values()):
                out.append(record)
        return out

    def write_tables(self, tables: Dict[str, Table]) -> None:
        for name, table in tables.items():
            ws = self._worksheet(name)
            if ws is None:
                ws = self._book.add_worksheet(title=name, rows=max(len(table.rows) + 50, 100), cols=max(len(table.headers), 8))
            ws.clear()
            values = [table.headers, *table.rows]
            if ws.row_count < len(values):
                ws.resize(rows=len(values) + 50)
            ws.update(values, "A1", value_input_option="RAW")
            ws.freeze(rows=1, cols=2 if name == board.TICKETS else 0)
            ws.format("1:1", {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.12, "green": 0.16, "blue": 0.22}})

    def edit_cells(self, edits: Sequence[Tuple[int, str, str]]) -> List[str]:
        ws = self._worksheet(board.TICKETS)
        if ws is None:
            raise KeyError("spreadsheet has no Tickets sheet")
        values = ws.get_all_values()
        headers = {h.strip(): i for i, h in enumerate(values[0])} if values else {}
        id_col = headers.get("Ticket ID")
        if id_col is None:
            raise KeyError("Tickets sheet has no 'Ticket ID' column")
        rows: Dict[int, int] = {}
        for r, row in enumerate(values[1:], start=2):
            ticket_id = board.parse_ticket_id(row[id_col] if id_col < len(row) else "")
            if ticket_id is not None and ticket_id not in rows:
                rows[ticket_id] = r
        problems: List[str] = []
        updates = []
        for ticket_id, column, value in edits:
            if ticket_id not in rows:
                problems.append(f"ticket {ticket_id} is not on the Tickets sheet")
            elif column not in headers:
                problems.append(f"no column named {column!r}")
            else:
                cell = self._gspread.utils.rowcol_to_a1(rows[ticket_id], headers[column] + 1)
                updates.append({"range": cell, "values": [[value]]})
        if updates:
            ws.batch_update(updates, value_input_option="RAW")
        return problems
