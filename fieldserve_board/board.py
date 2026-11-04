"""Sheet vocabulary: columns, how a ticket becomes a row, derived columns.

The workflow module speaks in tickets; this module speaks in sheet rows.
Shared by the sync engine, ``sheet.py apply`` and the web API so all three
agree on what a cell means.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Mapping, Optional, Tuple

from .extract import extract
from .models import DOCUMENT_FIELDS, EDITABLE_FIELDS, STATUS_CODES, STATUS_LABELS, Ticket
from .roster import Roster
from .workflow import Evaluation, TicketView, evaluate

TICKETS = "Tickets"
SUMMARY = "Summary"
NOISE = "Noise"
CONFLICTS = "Conflicts"
ACTIVITY = "Activity"
ROSTER = "Roster"

TICKET_COLUMNS = [
    "Ticket ID",
    "Subject",
    "Status",
    "Engineer",
    "Manager",
    "Purchase Order",
    "Delivery Note",
    "Work Report",
    "Invoice",
    "Stage",
    "Action Owner",
    "Integrity",
    "Store Code",
    "Store",
    "Job Type",
    "Requester",
    "Updated At",
]
FIELD_TO_COLUMN = {
    "status": "Status",
    "engineer": "Engineer",
    "manager": "Manager",
    "purchase_order": "Purchase Order",
    "delivery_note": "Delivery Note",
    "work_report": "Work Report",
    "invoice": "Invoice",
}
COLUMN_TO_FIELD = {v: k for k, v in FIELD_TO_COLUMN.items()}
DERIVED_COLUMNS = ["Stage", "Action Owner", "Integrity", "Store Code", "Store", "Job Type"]
FIELDS = list(EDITABLE_FIELDS)

Edit = Tuple[int, str, str]  # (ticket id, column, value)


def canon(field: str, value: str, roster: Roster) -> str:
    """Canonical form of a field value, for *comparison* and sheet input.

    Case and spacing never count as an edit for names and statuses; document
    text is compared exactly (apart from outer whitespace).
    """
    text = " ".join((value or "").split()) if field in ("status", "engineer", "manager") else (value or "").strip()
    if field == "status":
        for label in STATUS_CODES:
            if label.casefold() == text.casefold():
                return label
        return text
    if field == "engineer":
        agent = roster.find(text, "engineer")
        return agent.name if agent else text
    if field == "manager":
        agent = roster.find(text, "manager")
        return agent.name if agent else text
    return text


def api_values(ticket: Ticket, roster: Roster) -> Dict[str, str]:
    """A ticket's editable fields in sheet vocabulary."""
    return {
        "status": ticket.status_label(),
        "engineer": roster.engineer_name(ticket.engineer_id),
        "manager": ticket.manager,
        "purchase_order": ticket.purchase_order,
        "delivery_note": ticket.delivery_note,
        "work_report": ticket.work_report,
        "invoice": ticket.invoice,
    }


def view_of(ticket_id: int, values: Mapping[str, str], roster: Roster) -> TicketView:
    c = lambda f: canon(f, values.get(f, ""), roster)  # noqa: E731
    return TicketView(
        id=ticket_id,
        status=c("status"),
        engineer=c("engineer"),
        manager=values.get("manager", "").strip(),
        purchase_order=c("purchase_order"),
        delivery_note=c("delivery_note"),
        work_report=c("work_report"),
        invoice=c("invoice"),
    )


def evaluate_values(ticket_id: int, values: Mapping[str, str], roster: Roster) -> Evaluation:
    return evaluate(view_of(ticket_id, values, roster), roster)


def build_row(
    ticket_id: int,
    values: Mapping[str, str],
    *,
    subject: str,
    requester: str,
    updated_at: str,
    roster: Roster,
    requester_name: str = "",
) -> Dict[str, str]:
    """A full Tickets-sheet row, derived columns included."""
    evaluation = evaluate_values(ticket_id, values, roster)
    info = extract(subject, requester, requester_name)
    row = {
        "Ticket ID": str(ticket_id),
        "Subject": subject,
        "Stage": evaluation.stage,
        "Action Owner": evaluation.action_owner,
        "Integrity": evaluation.integrity,
        "Store Code": info.store_code,
        "Store": info.store_name,
        "Job Type": info.job_type,
        "Requester": requester,
        "Updated At": updated_at,
    }
    for field, column in FIELD_TO_COLUMN.items():
        row[column] = values.get(field, "")
    return row


def row_values(row: Mapping[str, str], roster: Roster) -> Dict[str, str]:
    """Editable field values from a sheet row, canonicalised as a human meant them."""
    return {f: canon(f, row.get(FIELD_TO_COLUMN[f], ""), roster) for f in FIELDS}


def parse_ticket_id(text: str) -> Optional[int]:
    raw = (text or "").strip()
    if raw.endswith(".0"):
        raw = raw[:-2]
    return int(raw) if raw.isdigit() else None


def derived_edits(rows: Iterable[Mapping[str, str]], roster: Roster) -> List[Edit]:
    """Cell edits that bring Stage / Action Owner / Integrity in line with a row.

    This is what a spreadsheet formula would do after a human edit, done
    locally (no API call) so ``sheet.py apply`` leaves the sheet consistent.
    """
    edits: List[Edit] = []
    for row in rows:
        ticket_id = parse_ticket_id(row.get("Ticket ID", ""))
        if ticket_id is None:
            continue
        evaluation = evaluate_values(ticket_id, row_values(row, roster), roster)
        for column, value in (
            ("Stage", evaluation.stage),
            ("Action Owner", evaluation.action_owner),
            ("Integrity", evaluation.integrity),
        ):
            if (row.get(column) or "") != value:
                edits.append((ticket_id, column, value))
    return edits


def validate_push(field: str, value: str, roster: Roster) -> Optional[str]:
    """Return a reason the API would refuse this value, else None."""
    if field == "status":
        return None if value in STATUS_CODES else f"unknown status '{value}' (use {', '.join(STATUS_CODES)})"
    if field == "engineer":
        if not value:
            return None
        return None if roster.find(value, "engineer") else f"'{value}' is not an Engineer on the roster"
    if field == "manager":
        if not value:
            return None
        return None if roster.find(value, "manager") else f"'{value}' is not a Manager on the roster"
    return None


CLEAR_NULL = "null"  # send JSON null
CLEAR_EMPTY = "empty"  # send ""


def clear_styles(field: str) -> List[str]:
    """Ways to ask the API to blank a field, in the order to try them.

    The live API answers 200 to a clear it does not understand and leaves the
    value alone, so the engine tries each style and checks the result. An
    engineer id can only be null. For documents the live API answers
    ``400 invoice must be a string`` to null, so the empty string goes first.
    """
    return [CLEAR_NULL] if field == "engineer" else [CLEAR_EMPTY, CLEAR_NULL]


def api_payload(field: str, value: str, roster: Roster, clear_style: str = CLEAR_NULL) -> Dict[str, object]:
    """The sparse PUT body for one field."""
    if field == "status":
        return {"status": STATUS_CODES[value]}
    if field == "engineer":
        agent = roster.find(value, "engineer") if value else None
        return {"engineer_id": agent.id if agent else None}
    blank = None if clear_style == CLEAR_NULL else ""
    if field == "manager":
        agent = roster.find(value, "manager") if value else None
        if agent:
            return {"manager": agent.name}
        return {"manager": value if value else blank}
    if field in DOCUMENT_FIELDS:
        return {field: value if value else blank}
    raise KeyError(field)


STATUS_LABEL_LIST = list(STATUS_LABELS.values())
