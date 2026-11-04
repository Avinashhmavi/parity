"""Read model and commands behind the HTTP API. No FastAPI imports here."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .. import board
from ..backends.base import BoardBackend
from ..config import Settings
from ..engine import SyncEngine
from ..locking import file_lock
from ..models import DOCUMENT_FIELDS
from ..roster import Roster
from ..state import State, StateStore
from ..summary import stage_counts, workload
from ..workflow import STAGES, classify_document, evaluate

CACHE_TTL_SECONDS = 2.0
PAGE_SIZE_MAX = 200


class ValidationError(ValueError):
    pass


class NotFound(LookupError):
    pass


def _issues(text: str) -> List[str]:
    return [p.strip() for p in (text or "").split(";") if p.strip()]


@dataclass
class _Snapshot:
    at: float
    rows: List[Dict[str, str]]
    roster: Roster
    noise: List[Dict[str, str]]


class BoardService:
    def __init__(self, settings: Settings, backend: BoardBackend, store: StateStore, engine: Optional[SyncEngine] = None):
        self.settings = settings
        self.backend = backend
        self.store = store
        self.engine = engine
        self._cache: Optional[_Snapshot] = None
        self._cache_lock = threading.Lock()
        self._lock_path = store.path.with_suffix(".lock")

    # -- reading ---------------------------------------------------------

    def invalidate(self) -> None:
        with self._cache_lock:
            self._cache = None

    def _snapshot(self) -> _Snapshot:
        with self._cache_lock:
            if self._cache and time.monotonic() - self._cache.at < CACHE_TTL_SECONDS:
                return self._cache
        with file_lock(self._lock_path, timeout=60):
            rows = self.backend.read_table(board.TICKETS)
            roster = Roster.from_sheet_rows(self.backend.read_table(board.ROSTER))
            noise = self.backend.read_table(board.NOISE)
        snap = _Snapshot(time.monotonic(), rows, roster, noise)
        with self._cache_lock:
            self._cache = snap
        return snap

    def _item(self, row: Dict[str, str], baseline: Optional[Dict[str, Any]], roster: Roster) -> Dict[str, Any]:
        ticket_id = int(board.parse_ticket_id(row["Ticket ID"]))
        item: Dict[str, Any] = {
            "id": ticket_id,
            "subject": row.get("Subject", ""),
            "status": row.get("Status", ""),
            "engineer": row.get("Engineer", ""),
            "manager": row.get("Manager", ""),
            "stage": row.get("Stage", ""),
            "actionOwner": row.get("Action Owner", ""),
            "integrity": _issues(row.get("Integrity", "")),
            "storeCode": row.get("Store Code", ""),
            "store": row.get("Store", ""),
            "jobType": row.get("Job Type", ""),
            "requester": row.get("Requester", ""),
            "updatedAt": row.get("Updated At", ""),
            "documents": {
                f: {"value": row.get(board.FIELD_TO_COLUMN[f], ""), "state": classify_document(row.get(board.FIELD_TO_COLUMN[f], "")).value}
                for f in DOCUMENT_FIELDS
            },
        }
        if baseline is not None:
            item["unsynced"] = [
                board.FIELD_TO_COLUMN[f]
                for f in board.FIELDS
                if f in baseline and board.canon(f, baseline[f], roster) != board.canon(f, row.get(board.FIELD_TO_COLUMN[f], ""), roster)
            ]
        return item

    def board(
        self,
        *,
        q: str = "",
        stage: str = "",
        owner: str = "",
        status: str = "",
        job_type: str = "",
        flagged: bool = False,
        sort: str = "id",
        order: str = "asc",
        page: int = 1,
        page_size: int = 100,
    ) -> Dict[str, Any]:
        snap = self._snapshot()
        state = self.store.load()
        page_size = max(1, min(page_size, PAGE_SIZE_MAX))
        needle = q.strip().casefold()

        def keep(r: Dict[str, str]) -> bool:
            if stage and r.get("Stage") != stage:
                return False
            if owner and r.get("Action Owner") != owner:
                return False
            if status and r.get("Status") != status:
                return False
            if job_type and r.get("Job Type") != job_type:
                return False
            if flagged and not r.get("Integrity"):
                return False
            if needle:
                hay = " ".join((r.get(c) or "") for c in ("Ticket ID", "Subject", "Store Code", "Store", "Engineer", "Manager", "Action Owner", "Requester"))
                return needle in hay.casefold()
            return True

        filtered = [r for r in snap.rows if keep(r)]
        sort_keys = {
            "id": lambda r: board.parse_ticket_id(r.get("Ticket ID", "")) or 0,
            "stage": lambda r: (STAGES.index(r["Stage"]) if r.get("Stage") in STAGES else 99),
            "owner": lambda r: (r.get("Action Owner") or "~").casefold(),
            "status": lambda r: r.get("Status", ""),
            "updated": lambda r: r.get("Updated At", ""),
        }
        key = sort_keys.get(sort, sort_keys["id"])
        filtered.sort(key=key, reverse=(order == "desc"))
        total = len(filtered)
        start = (max(page, 1) - 1) * page_size
        items = [self._item(r, state.baseline.get(str(board.parse_ticket_id(r["Ticket ID"])), {}).get("values"), snap.roster) for r in filtered[start : start + page_size]]
        return {"items": items, "total": total, "page": max(page, 1), "pageSize": page_size}

    def ticket(self, ticket_id: int) -> Dict[str, Any]:
        snap = self._snapshot()
        row = next((r for r in snap.rows if board.parse_ticket_id(r.get("Ticket ID", "")) == ticket_id), None)
        if row is None:
            raise NotFound(f"ticket {ticket_id} is not on the board")
        state = self.store.load()
        base = state.baseline.get(str(ticket_id), {}).get("values")
        item = self._item(row, base, snap.roster)
        evaluation = evaluate(board.view_of(ticket_id, board.evaluation_values(row, snap.roster), snap.roster), snap.roster)
        item["steps"] = [
            {"key": s.key, "label": s.label, "status": s.status.value, "owner": s.owner, "detail": s.detail} for s in evaluation.steps
        ]
        item["options"] = self.options(snap.roster)
        return item

    @staticmethod
    def options(roster: Roster) -> Dict[str, List[str]]:
        return {
            "status": list(board.STATUS_LABEL_LIST),
            "engineers": [a.name for a in roster.engineers],
            "managers": [a.name for a in roster.managers],
        }

    def summary(self) -> Dict[str, Any]:
        snap = self._snapshot()
        rows = snap.rows
        done = sum(1 for r in rows if r.get("Stage") == "Done")
        return {
            "workload": workload(rows, snap.roster),
            "stages": stage_counts(rows),
            "totals": {
                "tickets": len(rows),
                "pending": len(rows) - done,
                "done": done,
                "flagged": sum(1 for r in rows if r.get("Integrity")),
                "noise": len(snap.noise),
            },
        }

    def facets(self) -> Dict[str, Any]:
        snap = self._snapshot()
        statuses = sorted({r.get("Status", "") for r in snap.rows if r.get("Status")})
        job_types = sorted({r.get("Job Type", "") for r in snap.rows if r.get("Job Type")})
        owners = sorted({r.get("Action Owner", "") for r in snap.rows if r.get("Action Owner")}, key=str.casefold)
        return {"stages": list(STAGES), "statuses": statuses, "jobTypes": job_types, "owners": owners, **self.options(snap.roster)}

    def noise(self) -> List[Dict[str, str]]:
        return [
            {"id": r.get("Ticket ID", ""), "subject": r.get("Subject", ""), "requester": r.get("Requester", ""), "reason": r.get("Reason", "")}
            for r in self._snapshot().noise
        ]

    def conflicts(self) -> List[Dict[str, Any]]:
        return list(reversed(self.store.load().conflicts[-200:]))

    def activity(self) -> List[Dict[str, Any]]:
        return list(reversed(self.store.load().activity[-200:]))

    def sync_info(self) -> Dict[str, Any]:
        state: State = self.store.load()
        return {"lastSync": state.last_sync or None, "tickets": len(state.baseline)}

    # -- commands --------------------------------------------------------

    def edit(self, ticket_id: int, changes: Dict[str, str]) -> Dict[str, Any]:
        """Type values into the sheet like a human; the next sync pushes them."""
        snap = self._snapshot()
        if not changes:
            raise ValidationError("no changes given")
        unknown = set(changes) - set(board.FIELDS)
        if unknown:
            raise ValidationError(f"not editable: {', '.join(sorted(unknown))}")
        if not any(board.parse_ticket_id(r.get("Ticket ID", "")) == ticket_id for r in snap.rows):
            raise NotFound(f"ticket {ticket_id} is not on the board")
        edits: List[board.Edit] = []
        for name, raw in changes.items():
            value = board.canon(name, raw if isinstance(raw, str) else "", snap.roster)
            reason = board.validate_push(name, value, snap.roster)
            if reason:
                raise ValidationError(f"{board.FIELD_TO_COLUMN[name]}: {reason}")
            edits.append((ticket_id, board.FIELD_TO_COLUMN[name], value))
        with file_lock(self._lock_path, timeout=60):
            problems = self.backend.edit_cells(edits)
            rows = [r for r in self.backend.read_table(board.TICKETS) if board.parse_ticket_id(r.get("Ticket ID", "")) == ticket_id]
            problems += self.backend.edit_cells(board.derived_edits(rows, snap.roster))
        if problems:
            raise ValidationError("; ".join(problems))
        self.invalidate()
        return self.ticket(ticket_id)

    def run_sync(self, mode: str = "full"):
        if self.engine is None:
            raise RuntimeError("no API key configured; the board is read-only")
        try:
            return self.engine.run(mode)
        finally:
            self.invalidate()
