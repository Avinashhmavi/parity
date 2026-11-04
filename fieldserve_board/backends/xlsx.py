"""Excel backend (openpyxl). The default, and needs no credentials.

Stage / Action Owner / Integrity are written as values, not formulas. A
formula written by openpyxl has no cached result until Excel recalculates, so
anything that reads the file without Excel (a CSV export, a grader, CI) would
see blanks. Values are always readable; the cost is that they refresh on the
next sync or ``sheet.py apply``, not live in Excel. See README, "Decisions".
"""

from __future__ import annotations

import os
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.formatting.rule import CellIsRule, FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.worksheet import Worksheet

from .. import board
from .base import BoardBackend, Table

HEADER_FILL = PatternFill("solid", fgColor="1F2937")
HEADER_FONT = Font(bold=True, color="FFFFFF")
DERIVED_FILL = PatternFill("solid", fgColor="EEF2F7")
DERIVED_HEADER_FILL = PatternFill("solid", fgColor="475569")
WIDTHS = {
    "Ticket ID": 10,
    "Subject": 52,
    "Status": 11,
    "Engineer": 20,
    "Manager": 20,
    "Purchase Order": 28,
    "Delivery Note": 28,
    "Work Report": 28,
    "Invoice": 28,
    "Stage": 17,
    "Action Owner": 20,
    "Integrity": 36,
    "Store Code": 11,
    "Store": 18,
    "Job Type": 14,
    "Requester": 30,
    "Updated At": 22,
}
SHEET_ORDER = [board.TICKETS, board.SUMMARY, board.NOISE, board.CONFLICTS, board.ACTIVITY, board.ROSTER]


def cell_text(value: object) -> str:
    """Cell value as a human sees it: ``105.0`` -> ``105``, ``None`` -> ``""``."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


class XlsxBackend(BoardBackend):
    name = "xlsx"

    def __init__(self, path: Path):
        self.path = Path(path)

    def describe(self) -> str:
        return f"xlsx:{self.path}"

    # -- reading ---------------------------------------------------------

    def _load(self) -> Workbook:
        if not self.path.exists():
            return Workbook()
        return load_workbook(self.path)

    def read_table(self, name: str) -> List[Dict[str, str]]:
        if not self.path.exists():
            return []
        wb = load_workbook(self.path, read_only=True, data_only=True)
        try:
            if name not in wb.sheetnames:
                return []
            rows = wb[name].iter_rows(values_only=True)
            try:
                headers = [cell_text(h).strip() for h in next(rows)]
            except StopIteration:
                return []
            out: List[Dict[str, str]] = []
            for values in rows:
                record = {h: cell_text(v) for h, v in zip(headers, values) if h}
                if any(v.strip() for v in record.values()):
                    out.append(record)
            return out
        finally:
            wb.close()

    # -- writing ---------------------------------------------------------

    def write_tables(self, tables: Dict[str, Table]) -> None:
        wb = self._load()
        if wb.sheetnames == ["Sheet"] and wb["Sheet"].max_row == 1 and wb["Sheet"]["A1"].value is None:
            del wb["Sheet"]
        for name, table in tables.items():
            created = name not in wb.sheetnames
            ws = wb.create_sheet(name) if created else wb[name]
            self._fill(ws, table)
            self._style(ws, name, table, created, tables)
        self._order_sheets(wb)
        wb.active = wb.sheetnames.index(board.TICKETS) if board.TICKETS in wb.sheetnames else 0
        self._save(wb)

    @staticmethod
    def _fill(ws: Worksheet, table: Table) -> None:
        if ws.max_row > 0:
            ws.delete_rows(1, ws.max_row)
        ws.append(table.headers)
        for row in table.rows:
            ws.append(row)

    def _style(self, ws: Worksheet, name: str, table: Table, created: bool, tables: Dict[str, Table]) -> None:
        headers = table.headers
        for idx, header in enumerate(headers, start=1):
            cell = ws.cell(row=1, column=idx)
            derived = name == board.TICKETS and header in board.DERIVED_COLUMNS
            cell.fill = DERIVED_HEADER_FILL if derived else HEADER_FILL
            cell.font = HEADER_FONT
            cell.alignment = Alignment(vertical="center")
            if derived:
                cell.comment = Comment("Computed by the sync. Edits here are ignored and overwritten.", "FieldServe Board")
            if created:
                ws.column_dimensions[get_column_letter(idx)].width = WIDTHS.get(header, 18)
        ws.freeze_panes = "C2" if name == board.TICKETS else "A2"
        ws.sheet_view.zoomScale = 100
        if table.rows:
            ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(table.rows) + 1}"
        else:
            ws.auto_filter.ref = None
        if name == board.TICKETS:
            self._style_tickets(ws, headers, len(table.rows), tables.get(board.ROSTER))

    def _style_tickets(self, ws: Worksheet, headers: List[str], n: int, roster: Table | None) -> None:
        col = {h: get_column_letter(i) for i, h in enumerate(headers, start=1)}
        last = max(n + 1, 2)
        thin = Side(style="thin", color="E2E8F0")
        for row in ws.iter_rows(min_row=2, max_row=last):
            for cell in row:
                header = headers[cell.column - 1] if cell.column <= len(headers) else ""
                cell.border = Border(bottom=thin)
                if header in board.DERIVED_COLUMNS:
                    cell.fill = DERIVED_FILL

        ws.data_validations.dataValidation = []
        if "Status" in col:
            dv = DataValidation(type="list", formula1='"Open,Pending,Resolved,Closed"', allow_blank=False, errorStyle="warning")
            dv.error = "Status should be Open, Pending, Resolved or Closed."
            dv.add(f"{col['Status']}2:{col['Status']}{last}")
            ws.add_data_validation(dv)
        if roster is not None:
            for header, list_header in (("Engineer", "Engineers"), ("Manager", "Managers")):
                if header not in col or list_header not in roster.headers:
                    continue
                idx = roster.headers.index(list_header)
                count = sum(1 for r in roster.rows if r[idx])
                if not count:
                    continue
                letter = get_column_letter(idx + 1)
                dv = DataValidation(
                    type="list", formula1=f"={board.ROSTER}!${letter}$2:${letter}${count + 1}", allow_blank=True, errorStyle="warning"
                )
                dv.error = f"Pick a {header} from the roster."
                dv.add(f"{col[header]}2:{col[header]}{last}")
                ws.add_data_validation(dv)

        ws.conditional_formatting = type(ws.conditional_formatting)()
        if "Integrity" in col:
            rng = f"A2:{get_column_letter(len(headers))}{last}"
            ws.conditional_formatting.add(
                rng, FormulaRule(formula=[f'LEN(${col["Integrity"]}2)>0'], fill=PatternFill("solid", bgColor="FDE8E8"))
            )
        if "Stage" in col:
            ws.conditional_formatting.add(
                f"{col['Stage']}2:{col['Stage']}{last}",
                CellIsRule(operator="equal", formula=['"Done"'], font=Font(color="15803D", bold=True)),
            )

    @staticmethod
    def _order_sheets(wb: Workbook) -> None:
        known = [n for n in SHEET_ORDER if n in wb.sheetnames]
        extra = [n for n in wb.sheetnames if n not in SHEET_ORDER]
        wb._sheets = [wb[n] for n in known + extra]

    def _save(self, wb: Workbook) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".board-", suffix=".xlsx")
        os.close(fd)
        try:
            wb.save(tmp)
            os.replace(tmp, self.path)
        except PermissionError as exc:
            os.unlink(tmp)
            raise PermissionError(f"cannot write {self.path}: is it open in Excel? Close it and retry.") from exc
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def edit_cells(self, edits: Sequence[Tuple[int, str, str]]) -> List[str]:
        if not edits:
            return []
        if not self.path.exists():
            raise FileNotFoundError(f"{self.path} does not exist yet; run sync.py first")
        wb = load_workbook(self.path)
        if board.TICKETS not in wb.sheetnames:
            raise KeyError("workbook has no Tickets sheet")
        ws = wb[board.TICKETS]
        headers = {cell_text(c.value).strip(): c.column for c in ws[1] if c.value is not None}
        id_col = headers.get("Ticket ID")
        if id_col is None:
            raise KeyError("Tickets sheet has no 'Ticket ID' column")
        rows = {}
        for r in range(2, ws.max_row + 1):
            ticket_id = board.parse_ticket_id(cell_text(ws.cell(row=r, column=id_col).value))
            if ticket_id is not None and ticket_id not in rows:
                rows[ticket_id] = r
        problems: List[str] = []
        for ticket_id, column, value in edits:
            if ticket_id not in rows:
                problems.append(f"ticket {ticket_id} is not on the Tickets sheet")
            elif column not in headers:
                problems.append(f"no column named {column!r}")
            else:
                ws.cell(row=rows[ticket_id], column=headers[column]).value = value if value != "" else None
        self._save(wb)
        return problems
