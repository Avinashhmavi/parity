"""Field-level three-way merge. Pure: no I/O, fully unit-tested.

For every editable field of a ticket we hold three values:

``base``   what both sides agreed on at the last sync
``sheet``  what the spreadsheet says now
``api``    what the helpdesk says now

Rules, in order:

1. ``sheet == api``        already agree; nothing to do.
2. ``sheet == base``       the cell was not touched, so any difference is a
                           server-side change. **Take the API.** This is the
                           guarantee that a stale, unchanged cell can never
                           overwrite a fresh server change.
3. ``api == base``         only the sheet changed. **Push the sheet value.**
4. otherwise               both changed to different values: a conflict.
                           Resolved by ``policy`` (default: the API wins,
                           because it is the system of record and may already
                           have been acted on by someone else). The losing
                           value is recorded so it can be re-applied by hand.

Because this runs per field, a ticket changed on both sides still merges
cleanly when the edits touch different fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Mapping, Optional

API = "api"
SHEET = "sheet"


@dataclass
class Conflict:
    ticket_id: int
    field: str
    base: str
    sheet: str
    api: str
    winner: str  # "api" or "sheet"
    reason: str = "both sides changed"


@dataclass
class MergeResult:
    values: Dict[str, str] = field(default_factory=dict)  # merged value per field
    push: Dict[str, str] = field(default_factory=dict)  # fields to PUT (desired value)
    from_api: List[str] = field(default_factory=list)  # fields where the sheet must take the API value
    conflicts: List[Conflict] = field(default_factory=list)


def merge_ticket(
    ticket_id: int,
    base: Optional[Mapping[str, str]],
    sheet: Optional[Mapping[str, str]],
    api: Mapping[str, str],
    fields: List[str],
    policy: str = API,
    key: Callable[[str, str], str] = lambda _field, value: value,
) -> MergeResult:
    """Merge one ticket.

    ``base`` is None for a ticket we have never synced; ``sheet`` is None when
    the ticket has no row yet. With no baseline we cannot tell who changed, so
    the API wins and any differing sheet value is logged as a conflict rather
    than silently dropped.

    ``key(field, value)`` canonicalises a value *for comparison only* (for
    example case-folding a manager name), so ``"priya nair"`` typed by a human
    is not mistaken for an edit of ``"Priya Nair"``. Returned values are always
    the original, un-canonicalised strings.
    """
    result = MergeResult()
    for name in fields:
        a = api.get(name, "")
        s = sheet.get(name, "") if sheet is not None else a
        if sheet is None or key(name, s) == key(name, a):
            result.values[name] = a
            continue

        if base is None:
            result.values[name] = a
            result.from_api.append(name)
            result.conflicts.append(Conflict(ticket_id, name, "", s, a, API, "no baseline for this ticket"))
            continue

        b = base.get(name, "")
        if key(name, s) == key(name, b):
            result.values[name] = a
            result.from_api.append(name)
        elif key(name, a) == key(name, b):
            result.values[name] = s
            result.push[name] = s
        else:
            winner = policy if policy in (API, SHEET) else API
            result.conflicts.append(Conflict(ticket_id, name, b, s, a, winner))
            if winner == SHEET:
                result.values[name] = s
                result.push[name] = s
            else:
                result.values[name] = a
                result.from_api.append(name)
    return result
