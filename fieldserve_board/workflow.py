"""The six-step ticket workflow. Pure functions, no I/O.

A ticket owes six steps in order. The first unmet step is its *stage* and the
owner of that step is its *action owner*. Everything here follows section 3 of
the brief literally:

====  =================  ==============================  =====================
 #    Step               Met when                        Owner
====  =================  ==============================  =====================
 1    Assign Manager     manager is non-empty            Coordinator by parity
 2    Assign Engineer    engineer_id is set              the ticket's Manager
 3    Purchase Order     purchase_order is a URL         the ticket's Manager
 4    Delivery Note      delivery_note is a URL or NA    Finance
 5    Work Report        work_report is a URL            the ticket's Engineer
 6    Invoice            invoice is a URL or NA          Finance
====  =================  ==============================  =====================
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional
from urllib.parse import urlsplit

from .models import STATUS_LABELS
from .roster import UNKNOWN_ENGINEER_PREFIX, Roster

WAIVER = "NA"
DONE = "Done"

_WHITESPACE = re.compile(r"\s")


class DocState(str, Enum):
    URL = "url"  # a usable link: the document exists
    WAIVED = "waived"  # the exact text NA
    EMPTY = "empty"
    JUNK = "junk"  # anything else: "done", "asked Ravi", "ok", "NA " variants


def classify_document(value: Optional[str]) -> DocState:
    """Classify a raw document field.

    Only a well-formed http(s) URL or the exact waiver ``NA`` can ever count
    as a document. Whether ``NA`` is *accepted* depends on the document, see
    :data:`STEPS`; this function only says what the text is.
    """
    text = (value or "").strip()
    if not text:
        return DocState.EMPTY
    if text == WAIVER:
        return DocState.WAIVED
    if _is_url(text):
        return DocState.URL
    return DocState.JUNK


def _is_url(text: str) -> bool:
    if _WHITESPACE.search(text):
        return False
    try:
        parts = urlsplit(text)
    except ValueError:
        return False
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        return False
    host = parts.hostname or ""
    # "https://" + junk like "https://ok" has a netloc but is not a link a
    # human could follow. Require a dot or localhost-style host.
    return bool(host) and ("." in host or host == "localhost")


@dataclass(frozen=True)
class Step:
    key: str
    label: str  # also the sheet's Stage value
    field: str
    waivable: bool


STEPS = (
    Step("manager", "Assign Manager", "manager", False),
    Step("engineer", "Assign Engineer", "engineer", False),
    Step("purchase_order", "Purchase Order", "purchase_order", False),
    Step("delivery_note", "Delivery Note", "delivery_note", True),
    Step("work_report", "Work Report", "work_report", False),
    Step("invoice", "Invoice", "invoice", True),
)
STAGES = (*(s.label for s in STEPS), DONE)


class StepStatus(str, Enum):
    COMPLETE = "complete"
    PENDING = "pending"  # the current stage: first unmet step
    UPCOMING = "upcoming"  # unmet, but an earlier step is still open


@dataclass
class StepResult:
    key: str
    label: str
    status: StepStatus
    owner: str
    detail: str = ""  # e.g. "waived", "junk text"


@dataclass
class Evaluation:
    stage: str
    action_owner: str
    steps: List[StepResult]
    flags: List[str] = field(default_factory=list)

    @property
    def is_done(self) -> bool:
        return self.stage == DONE

    @property
    def integrity(self) -> str:
        return "; ".join(self.flags)


@dataclass(frozen=True)
class TicketView:
    """The slice of a ticket the workflow reads, in sheet vocabulary."""

    id: int
    status: str  # Open / Pending / Resolved / Closed or ""
    engineer: str  # roster name or ""
    manager: str
    purchase_order: str
    delivery_note: str
    work_report: str
    invoice: str


def _step_met(step: Step, view: TicketView) -> bool:
    if step.key == "manager":
        return bool(view.manager.strip())
    if step.key == "engineer":
        return bool(view.engineer.strip())
    state = classify_document(getattr(view, step.field))
    if state is DocState.URL:
        return True
    return step.waivable and state is DocState.WAIVED


def _step_owner(step: Step, view: TicketView, roster: Roster) -> str:
    if step.key == "manager":
        return roster.coordinator_for(view.id)
    if step.key in ("engineer", "purchase_order"):
        return roster.canonical_manager(view.manager)
    if step.key == "work_report":
        return view.engineer
    return roster.finance_owner()  # delivery note, invoice


def _step_detail(step: Step, view: TicketView) -> str:
    if step.field in ("manager", "engineer"):
        return ""
    state = classify_document(getattr(view, step.field))
    if state is DocState.WAIVED:
        return "waived" if step.waivable else "NA is not accepted here"
    if state is DocState.JUNK:
        return "not a link"
    return ""


def evaluate(view: TicketView, roster: Roster) -> Evaluation:
    """Work out stage, action owner, per-step state and integrity flags."""
    steps: List[StepResult] = []
    stage = DONE
    owner = ""
    for step in STEPS:
        met = _step_met(step, view)
        if met:
            status = StepStatus.COMPLETE
        elif stage == DONE:
            status = StepStatus.PENDING
            stage = step.label
            owner = _step_owner(step, view, roster)
        else:
            status = StepStatus.UPCOMING
        steps.append(
            StepResult(
                step.key,
                step.label,
                status,
                _step_owner(step, view, roster),
                _step_detail(step, view),
            )
        )
    return Evaluation(stage=stage, action_owner=owner, steps=steps, flags=_integrity_flags(view, roster, stage))


def _integrity_flags(view: TicketView, roster: Roster, stage: str) -> List[str]:
    flags: List[str] = []
    if view.status == STATUS_LABELS[5] and stage != DONE:
        flags.append(f"Closed but waiting on {stage}")
    if view.status == STATUS_LABELS[4] and classify_document(view.work_report) is not DocState.URL:
        flags.append("Resolved without Work Report")
    for step in STEPS:
        if step.field in ("manager", "engineer"):
            continue
        state = classify_document(getattr(view, step.field))
        if state is DocState.JUNK:
            flags.append(f"{step.label} is not a link")
        elif state is DocState.WAIVED and not step.waivable:
            flags.append(f"{step.label} cannot be NA")
    if view.manager.strip() and roster.find(view.manager, "manager") is None:
        flags.append("Manager not on roster")
    if view.engineer.startswith(UNKNOWN_ENGINEER_PREFIX):
        flags.append("Engineer not on roster")
    return flags
