"""Plain data types shared across the package. No I/O in here."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# Numeric helpdesk status <-> the label shown in the sheet.
STATUS_LABELS = {2: "Open", 3: "Pending", 4: "Resolved", 5: "Closed"}
STATUS_CODES = {label: code for code, label in STATUS_LABELS.items()}

# The fields a sheet edit may push back to the API. Everything else the
# sheet shows is read-only (the API answers 400 to it) or computed.
EDITABLE_FIELDS = (
    "status",
    "engineer",
    "manager",
    "purchase_order",
    "delivery_note",
    "work_report",
    "invoice",
)
DOCUMENT_FIELDS = ("purchase_order", "delivery_note", "work_report", "invoice")


@dataclass(frozen=True)
class Agent:
    id: int
    name: str
    role: str
    team: str = ""
    reports_to: str = ""  # the real API sends the manager's *name*, not an id


@dataclass
class Ticket:
    """A ticket as served by the API, normalised to the fields we care about.

    ``engineer_id`` is the foreign key; the human readable name is resolved
    against the roster by :class:`fieldserve_board.roster.Roster`.
    """

    id: int
    subject: str = ""
    status: Optional[int] = None
    engineer_id: Optional[int] = None
    manager: str = ""
    purchase_order: str = ""
    delivery_note: str = ""
    work_report: str = ""
    invoice: str = ""
    updated_at: str = ""
    created_at: str = ""
    requester_email: str = ""
    requester_name: str = ""
    # Fields the API sent as JSON null rather than "" (see FieldServeClient).
    null_fields: frozenset = field(default_factory=frozenset)

    def status_label(self) -> str:
        if self.status is None:
            return ""
        return STATUS_LABELS.get(self.status, f"Status {self.status}")
