"""Workload summary: how many tickets are waiting on each person right now."""

from __future__ import annotations

from collections import Counter
from typing import Dict, Iterable, List, Mapping

from .roster import COORDINATOR, ENGINEER, FINANCE, MANAGER, Roster
from .workflow import DONE, STAGES

ROLE_ORDER = (COORDINATOR, MANAGER, ENGINEER, FINANCE)


def workload(rows: Iterable[Mapping[str, str]], roster: Roster) -> List[Dict[str, object]]:
    """One entry per person: pending tickets and how many carry integrity flags.

    Everyone on the roster is listed, including people with nothing pending,
    so an idle engineer is visible. Owners that are not on the roster (a
    free-text manager name) appear as ``Unlisted`` rather than being dropped.
    """
    pending: Counter = Counter()
    flagged: Counter = Counter()
    for row in rows:
        owner = (row.get("Action Owner") or "").strip()
        if not owner or row.get("Stage") == DONE:
            continue
        pending[owner] += 1
        if (row.get("Integrity") or "").strip():
            flagged[owner] += 1

    out: List[Dict[str, object]] = []
    listed = set()
    for role in ROLE_ORDER:
        people = roster.with_role(role)
        entries = [
            {"person": a.name, "role": a.role, "pending": pending[a.name], "flagged": flagged[a.name]} for a in people
        ]
        entries.sort(key=lambda e: (-int(e["pending"]), str(e["person"])))
        out.extend(entries)
        listed.update(a.name for a in people)
    for owner in sorted(set(pending) - listed):
        out.append({"person": owner, "role": "Unlisted", "pending": pending[owner], "flagged": flagged[owner]})
    return out


def stage_counts(rows: Iterable[Mapping[str, str]]) -> Dict[str, int]:
    counts = Counter(row.get("Stage", "") for row in rows)
    return {stage: counts.get(stage, 0) for stage in STAGES}
