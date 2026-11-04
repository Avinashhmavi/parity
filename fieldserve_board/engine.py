"""One full two-way sync cycle between the FieldServe API and the board.

    pull   list every ticket (windowed by updated_since), read the roster
    read   read the sheet
    merge  per ticket, per field, three-way against the stored baseline
    push   PUT sheet edits to the API (re-checking each ticket first)
    write  write the merged result back to the sheet, then save the baseline

The ordering is deliberate: the API write is the only step that cannot be
retried blindly, so it happens after every decision is made and each pushed
ticket is re-read immediately beforehand. If the process dies after a push but
before the sheet write, the next run sees ``sheet == api`` and does nothing.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Set

from . import board
from .backends.base import BoardBackend, Table
from .client import EPOCH, ApiError, FieldServeClient, SharedRateLimiter, format_updated_since, parse_timestamp
from .config import Settings
from .extract import extract
from .locking import file_lock
from .merge import merge_ticket
from .models import Ticket
from .noise import classify
from .roster import Roster
from .state import State, StateStore
from .summary import workload

log = logging.getLogger(__name__)

MISSING_CHECK_LIMIT = 25
INCREMENTAL_OVERLAP_SECONDS = 60


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class SyncResult:
    ok: bool = True
    mode: str = "full"
    started_at: str = ""
    finished_at: str = ""
    duration_seconds: float = 0.0
    requests: int = 0
    tickets_seen: int = 0
    operational: int = 0
    noise: int = 0
    created: int = 0
    updated_from_api: int = 0
    pushed: int = 0
    conflicts: int = 0
    rejected: int = 0
    removed: int = 0
    errors: int = 0
    error: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class _Ticket:
    """Everything the engine tracks about one ticket during a cycle."""

    id: int
    values: Dict[str, str]  # latest API values (editable fields, sheet vocabulary)
    subject: str
    requester: str
    updated_at: str
    noise: str  # reason, or "" if operational
    requester_name: str = ""
    null_fields: Set[str] = field(default_factory=set)
    # outcome
    final: Dict[str, str] = field(default_factory=dict)
    base_override: Dict[str, str] = field(default_factory=dict)  # fields whose baseline must not advance


class SyncEngine:
    def __init__(
        self,
        client: FieldServeClient,
        backend: BoardBackend,
        store: StateStore,
        settings: Settings,
        *,
        lock_path=None,
        now: Callable[[], str] = utc_now,
    ):
        self.client = client
        self.backend = backend
        self.store = store
        self.settings = settings
        self.lock_path = lock_path or store.path.with_suffix(".lock")
        self._now = now

    # -- public ----------------------------------------------------------

    def run(self, mode: str = "full") -> SyncResult:
        if mode not in ("full", "incremental"):
            raise ValueError("mode must be 'full' or 'incremental'")
        with file_lock(self.lock_path):
            return self._run_locked(mode)

    # -- orchestration ---------------------------------------------------

    def _run_locked(self, mode: str) -> SyncResult:
        began = time.monotonic()
        requests_before = self.client.request_count
        state = self.store.load()
        result = SyncResult(mode=mode, started_at=self._now())
        events: List[Dict[str, Any]] = []
        try:
            self._cycle(state, mode, result, events)
        except Exception as exc:
            result.ok = False
            result.error = f"{type(exc).__name__}: {exc}"
            log.exception("sync failed")
            raise
        finally:
            result.finished_at = self._now()
            result.duration_seconds = round(time.monotonic() - began, 2)
            result.requests = self.client.request_count - requests_before
            state.last_sync = result.as_dict()
            state.activity.extend(events)
            try:
                self.store.save(state)
            except OSError:
                log.exception("could not save sync state")
        return result

    def _event(self, events: List[dict], kind: str, message: str, ticket_id: Optional[int] = None) -> None:
        events.append({"time": self._now(), "kind": kind, "ticket_id": ticket_id, "message": message})

    def _cycle(self, state: State, mode: str, result: SyncResult, events: List[dict]) -> None:
        roster = Roster(self.client.agents())
        since = self._since(state, mode)
        api_tickets = self.client.list_all(since)
        result.tickets_seen = len(api_tickets)

        tracked, removed = self._reconcile_known(state, mode, roster, api_tickets, events)
        result.removed = len(removed)
        for ticket_id in removed:
            self._event(events, "removed", "Ticket no longer exists on the API; removed from the sheet.", ticket_id)

        sheet_rows = self.backend.read_table(board.TICKETS)
        by_id, order, orphans = self._index_sheet(sheet_rows, events)

        for ticket in tracked.values():
            if ticket.noise:
                continue
            self._merge_and_push(ticket, state, by_id.get(ticket.id), roster, result, events)

        self._detect_noise_moves(tracked, by_id, events)
        rows_by_id, held = self._assemble_rows(tracked, by_id, roster)
        rows_by_id, held = self._hold_concurrent_edits(tracked, by_id, rows_by_id, held, roster, events)

        new_ids = [i for i in sorted(rows_by_id) if i not in order]
        result.created = sum(1 for i in new_ids if str(i) not in state.baseline)
        ordered = [i for i in order if i in rows_by_id] + new_ids
        ticket_rows = [rows_by_id[i] for i in ordered] + orphans

        result.operational = len(rows_by_id)
        result.noise = sum(1 for t in tracked.values() if t.noise)
        if result.created:
            self._event(events, "added", f"Added {result.created} ticket(s) to the sheet.")
        # The Activity sheet is built from the log, so this cycle's events must be
        # in it *before* the tables are written (otherwise it lags a sync behind).
        state.activity.extend(events)
        events.clear()

        tables = self._tables(ticket_rows, tracked, roster, state)
        self.backend.write_tables(tables)

        self._advance_baseline(state, tracked, held, mode)
        state.checkpoint = self._checkpoint(tracked, state.checkpoint)
        result.ok = True

    # -- pulling ---------------------------------------------------------

    @staticmethod
    def _since(state: State, mode: str) -> str:
        if mode == "full" or not state.checkpoint:
            return EPOCH
        stamp = parse_timestamp(state.checkpoint)
        if stamp is None:
            return EPOCH
        return format_updated_since(stamp - timedelta(seconds=INCREMENTAL_OVERLAP_SECONDS))

    def _to_tracked(self, ticket: Ticket, roster: Roster) -> _Ticket:
        info = extract(ticket.subject, ticket.requester_email, ticket.requester_name)
        verdict = classify(ticket.subject, ticket.requester_email, info, self.settings.trusted_domains)
        return _Ticket(
            id=ticket.id,
            values=board.api_values(ticket, roster),
            subject=ticket.subject,
            requester=ticket.requester_email,
            requester_name=ticket.requester_name,
            updated_at=ticket.updated_at,
            noise=verdict.reason if verdict.is_noise else "",
            null_fields=set(ticket.null_fields),
        )

    def _reconcile_known(self, state, mode, roster, api_tickets, events):
        """Combine the API listing with tickets we already know about."""
        tracked: Dict[int, _Ticket] = {tid: self._to_tracked(t, roster) for tid, t in api_tickets.items()}
        removed: List[int] = []
        known_missing = [int(i) for i in state.baseline if int(i) not in tracked]

        if mode == "full" and known_missing:
            if len(known_missing) > MISSING_CHECK_LIMIT:
                # A listing that suddenly lacks dozens of tickets is far more
                # likely a listing problem than dozens of deletions. Do not
                # touch them; treat as unchanged.
                log.warning("%d known tickets absent from a full listing; not removing any", len(known_missing))
                self._event(events, "warning", f"{len(known_missing)} known tickets were missing from the listing; kept as-is.")
            else:
                for ticket_id in known_missing:
                    try:
                        tracked[ticket_id] = self._to_tracked(self.client.get_ticket(ticket_id), roster)
                    except ApiError as exc:
                        if exc.status == 404:
                            removed.append(ticket_id)
                        else:
                            raise
                known_missing = []

        # Not returned and not checked (incremental mode, or too many missing):
        # unchanged since the baseline.
        for ticket_id in known_missing:
            snap = state.baseline[str(ticket_id)]
            tracked[ticket_id] = _Ticket(
                id=ticket_id,
                values=dict(snap["values"]),
                subject=snap.get("subject", ""),
                requester=snap.get("requester", ""),
                requester_name=snap.get("requester_name", ""),
                updated_at=snap.get("updated_at", ""),
                noise=snap.get("noise", ""),
            )
        return tracked, removed

    # -- sheet side ------------------------------------------------------

    def _index_sheet(self, rows, events):
        by_id: Dict[int, dict] = {}
        order: List[int] = []
        orphans: List[dict] = []
        for row in rows:
            ticket_id = board.parse_ticket_id(row.get("Ticket ID", ""))
            if ticket_id is None:
                orphans.append(row)
                self._event(events, "ignored", f"Row with Ticket ID '{row.get('Ticket ID', '')}' is not a ticket id; left untouched.")
            elif ticket_id in by_id:
                self._event(events, "ignored", f"Duplicate row for ticket {ticket_id}; the first one is used.", ticket_id)
            else:
                by_id[ticket_id] = row
                order.append(ticket_id)
        return by_id, order, orphans

    # -- merge + push ----------------------------------------------------

    def _merge_and_push(self, ticket: _Ticket, state: State, row, roster: Roster, result: SyncResult, events) -> None:
        base_snap = state.baseline.get(str(ticket.id))
        base = base_snap["values"] if base_snap else None
        sheet_vals = board.row_values(row, roster) if row is not None else None
        key = lambda f, v: board.canon(f, v, roster)  # noqa: E731
        policy = self.settings.conflict_policy

        merged = merge_ticket(ticket.id, base, sheet_vals, ticket.values, board.FIELDS, policy, key)
        if merged.push:
            merged, ticket = self._push(ticket, base, sheet_vals, roster, result, events, key, policy)
        else:
            result.updated_from_api += 1 if merged.from_api else 0

        for conflict in merged.conflicts:
            result.conflicts += 1
            state.conflicts.append({"time": self._now(), **asdict(conflict)})
            self._event(
                events,
                "conflict",
                f"{conflict.field}: {conflict.winner} won ({conflict.reason}). sheet='{conflict.sheet}' api='{conflict.api}'",
                ticket.id,
            )
        if not ticket.final:
            ticket.final = dict(merged.values)

    def _push(self, ticket: _Ticket, base, sheet_vals, roster: Roster, result, events, key, policy):
        """Send sheet edits for one ticket. Re-reads the ticket first."""
        try:
            fresh = self._to_tracked(self.client.get_ticket(ticket.id), roster)
        except ApiError as exc:
            result.errors += 1
            self._event(events, "error", f"Could not re-read before pushing: {exc.message}", ticket.id)
            merged = merge_ticket(ticket.id, base, sheet_vals, ticket.values, board.FIELDS, policy, key)
            ticket.final = {**merged.values, **{f: v for f, v in (sheet_vals or {}).items() if f in merged.push}}
            ticket.base_override = {f: (base or {}).get(f, "") for f in merged.push}
            return merged, ticket

        # Merge again against the fresh copy: if the server moved while we
        # were deciding, this is what keeps a stale cell from clobbering it.
        merged = merge_ticket(ticket.id, base, sheet_vals, fresh.values, board.FIELDS, policy, key)
        final = dict(merged.values)
        accepted: Dict[str, str] = {}
        for name, value in merged.push.items():
            reason = board.validate_push(name, value, roster)
            if reason:
                final[name] = fresh.values[name]
                result.rejected += 1
                self._event(events, "rejected", f"{board.FIELD_TO_COLUMN[name]}: {reason}; reverted to the server value.", ticket.id)
            else:
                accepted[name] = value

        updated: Optional[Ticket] = None
        pending_failed: Dict[str, str] = {}
        if accepted:
            updated, final, pending_failed = self._send(ticket, fresh, accepted, final, roster, result, events)

        if updated is not None:
            vals = board.api_values(updated, roster)
            final = {f: vals[f] for f in board.FIELDS}
            for name in pending_failed:
                final[name] = pending_failed[name]
            fresh.updated_at = updated.updated_at or fresh.updated_at
        ticket.values = fresh.values if updated is None else board.api_values(updated, roster)
        ticket.updated_at = fresh.updated_at
        ticket.null_fields = fresh.null_fields
        ticket.final = final
        ticket.base_override = {f: (base or {}).get(f, fresh.values[f]) for f in pending_failed}
        return merged, ticket

    def _send(self, ticket, fresh, accepted, final, roster, result, events):
        """PUT the accepted fields.

        Values are sent in one request (a refused batch is retried field by
        field so one bad value cannot block a good one). Blanking a field is
        sent on its own and *verified*: the live API answers 200 to a clear it
        does not understand and leaves the value untouched.
        """
        updated: Optional[Ticket] = None
        pending_failed: Dict[str, str] = {}
        sets = {n: v for n, v in accepted.items() if v != ""}
        clears = [n for n, v in accepted.items() if v == ""]

        def attempt(fields: Dict[str, str]) -> None:
            nonlocal updated
            try:
                body: Dict[str, object] = {}
                for name, value in fields.items():
                    body.update(board.api_payload(name, value, roster))
                got = self.client.update_ticket(ticket.id, body)
                updated = got if got is not None else self.client.get_ticket(ticket.id)
                result.pushed += len(fields)
                for name in fields:
                    self._event(events, "pushed", f"{board.FIELD_TO_COLUMN[name]} -> '{fields[name]}'", ticket.id)
            except ApiError as exc:
                if exc.is_rejection and len(fields) > 1:
                    for name, value in fields.items():
                        attempt({name: value})
                elif exc.is_rejection:
                    ((name, value),) = fields.items()
                    final[name] = fresh.values[name]
                    result.rejected += 1
                    self._event(
                        events, "rejected", f"{board.FIELD_TO_COLUMN[name]} '{value}' refused by the API: {exc.message}", ticket.id
                    )
                else:
                    for name, value in fields.items():
                        pending_failed[name] = value
                    result.errors += 1
                    self._event(events, "error", f"Push failed, will retry next sync: {exc.message}", ticket.id)

        def clear(name: str) -> None:
            nonlocal updated
            column = board.FIELD_TO_COLUMN[name]
            for style in board.clear_styles(name):
                try:
                    got = self.client.update_ticket(ticket.id, board.api_payload(name, "", roster, style))
                    now = got if got is not None else self.client.get_ticket(ticket.id)
                except ApiError as exc:
                    if exc.is_rejection:
                        continue  # this style is refused; try the next
                    pending_failed[name] = ""
                    result.errors += 1
                    self._event(events, "error", f"Push failed, will retry next sync: {exc.message}", ticket.id)
                    return
                updated = now
                if board.api_values(now, roster)[name] == "":
                    result.pushed += 1
                    self._event(events, "pushed", f"{column} cleared", ticket.id)
                    return
            final[name] = fresh.values[name]
            result.rejected += 1
            self._event(
                events,
                "rejected",
                f"{column}: the API accepted the request but kept the old value, so it cannot be cleared; reverted to the server value.",
                ticket.id,
            )

        if sets:
            attempt(sets)
        for name in clears:
            clear(name)
        return updated, final, pending_failed

    # -- assembling output -----------------------------------------------

    def _detect_noise_moves(self, tracked, by_id, events) -> None:
        for ticket in tracked.values():
            if ticket.noise and ticket.id in by_id:
                self._event(events, "noise", f"Moved off the board as noise: {ticket.noise}", ticket.id)

    def _assemble_rows(self, tracked, by_id, roster):
        rows: Dict[int, dict] = {}
        held: Dict[int, Set[str]] = {}
        for ticket in tracked.values():
            if ticket.noise:
                continue
            rows[ticket.id] = board.build_row(
                ticket.id,
                ticket.final,
                subject=ticket.subject,
                requester=ticket.requester,
                requester_name=ticket.requester_name,
                updated_at=ticket.updated_at,
                roster=roster,
            )
            held[ticket.id] = set(ticket.base_override)
        return rows, held

    def _hold_concurrent_edits(self, tracked, by_id, rows, held, roster, events):
        """Compare-and-swap on the sheet: never overwrite an edit made mid-sync."""
        latest_rows = self.backend.read_table(board.TICKETS)
        latest: Dict[int, dict] = {}
        for row in latest_rows:
            ticket_id = board.parse_ticket_id(row.get("Ticket ID", ""))
            if ticket_id is not None and ticket_id not in latest:
                latest[ticket_id] = row
        for ticket_id, row in rows.items():
            before, after = by_id.get(ticket_id), latest.get(ticket_id)
            if before is None or after is None:
                continue
            b, a = board.row_values(before, roster), board.row_values(after, roster)
            for name in board.FIELDS:
                if b[name] != a[name]:
                    column = board.FIELD_TO_COLUMN[name]
                    row[column] = after.get(column, "")
                    held[ticket_id].add(name)
                    self._event(events, "held", f"{column} was edited during the sync; kept your edit for the next one.", ticket_id)
            if held[ticket_id]:
                evaluation = board.evaluate_values(ticket_id, board.row_values(row, roster), roster)
                row.update({"Stage": evaluation.stage, "Action Owner": evaluation.action_owner, "Integrity": evaluation.integrity})
        return rows, held

    def _advance_baseline(self, state: State, tracked, held, mode: str) -> None:
        # Tickets that vanished from the API are dropped from the baseline.
        live = {str(i) for i in tracked}
        for key in [k for k in state.baseline if k not in live]:
            del state.baseline[key]
        for ticket in tracked.values():
            old = state.baseline.get(str(ticket.id))
            values = dict(ticket.final or ticket.values)
            for name in held.get(ticket.id, set()) | set(ticket.base_override):
                values[name] = (old["values"].get(name, ticket.values.get(name, "")) if old else ticket.values.get(name, ""))
            if ticket.noise:
                values = dict(ticket.values)
            state.baseline[str(ticket.id)] = {
                "values": values,
                "subject": ticket.subject,
                "requester": ticket.requester,
                "requester_name": ticket.requester_name,
                "updated_at": ticket.updated_at,
                "noise": ticket.noise,
            }

    @staticmethod
    def _checkpoint(tracked, current: str) -> str:
        best, best_text = parse_timestamp(current), current
        for ticket in tracked.values():
            stamp = parse_timestamp(ticket.updated_at)
            if stamp and (best is None or stamp > best):
                best, best_text = stamp, ticket.updated_at
        return best_text

    def _tables(self, ticket_rows, tracked, roster: Roster, state: State) -> Dict[str, Table]:
        pending = workload(ticket_rows, roster)
        engineers = [a.name for a in roster.engineers]
        managers = [a.name for a in roster.managers]
        roster_rows = []
        for i, entry in enumerate(roster.to_rows()):
            roster_rows.append(
                {
                    "ID": entry["id"],
                    "Name": entry["name"],
                    "Role": entry["role"],
                    "Team": entry["team"],
                    "Reports To": entry["reports_to"] or "",
                    "Engineers": engineers[i] if i < len(engineers) else "",
                    "Managers": managers[i] if i < len(managers) else "",
                }
            )
        for i in range(len(roster_rows), max(len(engineers), len(managers))):
            roster_rows.append(
                {"Engineers": engineers[i] if i < len(engineers) else "", "Managers": managers[i] if i < len(managers) else ""}
            )
        noise_rows = [
            {
                "Ticket ID": t.id,
                "Subject": t.subject,
                "Requester": t.requester,
                "Reason": t.noise,
                "Updated At": t.updated_at,
            }
            for t in sorted(tracked.values(), key=lambda t: t.id)
            if t.noise
        ]
        conflict_rows = [
            {
                "Time": c["time"],
                "Ticket ID": c["ticket_id"],
                "Field": board.FIELD_TO_COLUMN.get(c["field"], c["field"]),
                "Baseline": c["base"],
                "Sheet Value": c["sheet"],
                "API Value": c["api"],
                "Winner": c["winner"],
                "Reason": c["reason"],
            }
            for c in reversed(state.conflicts[-500:])
        ]
        activity_rows = [
            {"Time": a["time"], "Kind": a["kind"], "Ticket ID": a["ticket_id"] or "", "Message": a["message"]}
            for a in reversed(state.activity[-300:])
        ]
        summary_rows = [
            {"Person": p["person"], "Role": p["role"], "Pending Tickets": p["pending"], "With Integrity Issues": p["flagged"]}
            for p in pending
        ]
        h = lambda *names: list(names)  # noqa: E731
        return {
            board.TICKETS: Table.from_dicts(board.TICKET_COLUMNS, ticket_rows),
            board.SUMMARY: Table.from_dicts(h("Person", "Role", "Pending Tickets", "With Integrity Issues"), summary_rows),
            board.NOISE: Table.from_dicts(h("Ticket ID", "Subject", "Requester", "Reason", "Updated At"), noise_rows),
            board.CONFLICTS: Table.from_dicts(
                h("Time", "Ticket ID", "Field", "Baseline", "Sheet Value", "API Value", "Winner", "Reason"), conflict_rows
            ),
            board.ACTIVITY: Table.from_dicts(h("Time", "Kind", "Ticket ID", "Message"), activity_rows),
            board.ROSTER: Table.from_dicts(h("ID", "Name", "Role", "Team", "Reports To", "Engineers", "Managers"), roster_rows),
        }


def build_engine(settings: Settings) -> SyncEngine:
    from .backends import make_backend

    client = FieldServeClient(
        settings.base_url,
        settings.api_key,
        requests_per_minute=settings.requests_per_minute,
        timeout=settings.http_timeout,
        # One budget per API key, shared with the web app and any CLI run.
        limiter=SharedRateLimiter(settings.state_path.with_suffix(".rate"), settings.requests_per_minute),
    )
    return SyncEngine(client, make_backend(settings), StateStore(settings.state_path), settings)
