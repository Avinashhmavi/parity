"""Write-path check against a REAL FieldServe API.

Temporarily changes ONE ticket through the whole stack (sheet edit -> sync ->
PUT -> GET), asserts the API really took the change, then restores every
field it touched. It exists because reading is easy to verify and writing is
where real-API surprises live (null vs "" for cleared fields, validation
rules, whether a PUT returns the ticket).

    python3 -m fieldserve_board.devtools.live_check --yes [--ticket 195765]

Only run it against a dataset you are allowed to modify (the take-home gives
each candidate a private copy). Restoration runs in a ``finally`` block.
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Callable, List, Optional, Tuple

from .. import board
from ..client import ApiError, FieldServeClient
from ..config import Settings
from ..engine import SyncEngine, build_engine
from ..models import STATUS_LABELS, Ticket

URL_A = "https://example.com/live-check/a.pdf"
URL_B = "https://example.com/live-check/b.pdf"
URL_C = "https://example.com/live-check/c.pdf"

Result = Tuple[str, bool, str]


class Check:
    def __init__(self, engine: SyncEngine, ticket_id: int):
        self.engine = engine
        self.client: FieldServeClient = engine.client
        self.id = ticket_id
        self.results: List[Result] = []

    def api(self) -> Ticket:
        return self.client.get_ticket(self.id)

    def sync(self):
        # One full listing costs ~23 of the 60 requests a minute; an incremental
        # one costs ~2 and is what the web app uses between full syncs.
        return self.engine.run("incremental")

    def edit(self, column: str, value: str) -> None:
        problems = self.engine.backend.edit_cells([(self.id, column, value)])
        if problems:
            raise AssertionError(f"could not edit the sheet: {problems}")

    def sheet_value(self, column: str) -> str:
        for row in self.engine.backend.read_table(board.TICKETS):
            if board.parse_ticket_id(row.get("Ticket ID", "")) == self.id:
                return row.get(column, "")
        raise AssertionError("ticket missing from the sheet")

    def run(self, name: str, fn: Callable[[], None]) -> None:
        try:
            fn()
        except (AssertionError, ApiError) as exc:
            self.results.append((name, False, str(exc)))
            print(f"FAIL  {name}: {exc}")
        else:
            self.results.append((name, True, ""))
            print(f"PASS  {name}")


def pick_ticket(engine: SyncEngine, wanted: Optional[int]) -> int:
    rows = engine.backend.read_table(board.TICKETS)
    if wanted is not None:
        return wanted
    for row in rows:
        if row.get("Status") in ("Open", "Pending") and row.get("Engineer") and row.get("Manager") and not row.get("Integrity"):
            return int(row["Ticket ID"])
    for row in rows:
        if row.get("Engineer") and row.get("Manager"):
            return int(row["Ticket ID"])
    return int(rows[0]["Ticket ID"])


def run_checks(engine: SyncEngine, ticket_id: int) -> List[Result]:
    c = Check(engine, ticket_id)
    first = c.sync()
    assert first.ok, "initial sync failed"
    original = c.api()
    roster = board_roster(engine)
    print(f"ticket #{ticket_id}: status={original.status_label()} engineer_id={original.engineer_id} manager={original.manager!r}")
    touched = {"status", "engineer_id", "invoice", "work_report"}

    try:
        def doc_roundtrip():
            c.edit("Invoice", URL_A)
            r = c.sync()
            assert r.pushed == 1 and r.errors == 0, f"expected 1 push, got {r.pushed} (errors={r.errors}, rejected={r.rejected})"
            assert c.api().invoice == URL_A, f"API invoice is {c.api().invoice!r}"
            c.edit("Invoice", original.invoice)
            r = c.sync()
            assert r.errors == 0, f"push errors while restoring: {r.errors}"
            if c.api().invoice.strip() != original.invoice:
                # Fine only if the engine noticed and the sheet tells the truth; the final restore step fixes the ticket.
                assert r.rejected == 1 and c.sheet_value("Invoice") == c.api().invoice, "the API ignored the clear and the sheet lied"
                print("      (the API ignored clearing the invoice; refused cleanly)")

        c.run("document: set a link, then restore the original value", doc_roundtrip)

        def clear_semantics():
            """Report, from raw PUTs, which blank the API understands (it answers 200 either way)."""
            c.client.update_ticket(ticket_id, {"invoice": URL_A})
            findings = []
            for label, blank in (("null", None), ("empty string", "")):
                c.client.update_ticket(ticket_id, {"invoice": blank})
                cleared = c.api().invoice == ""
                findings.append(f"{label}={'clears' if cleared else 'IGNORED'}")
                if cleared:
                    break
                c.client.update_ticket(ticket_id, {"invoice": URL_A})
            print("      document blank styles:", ", ".join(findings))
            c.client.update_ticket(ticket_id, {"engineer_id": None})
            eng = "clears" if c.api().engineer_id is None else "IGNORED"
            print(f"      engineer_id null: {eng}")
            c.client.update_ticket(ticket_id, {"engineer_id": original.engineer_id})
            assert any("clears" in f for f in findings), "the API accepts no way of blanking a document"

        c.run("probe: which blank values the API honours (informational)", clear_semantics)

        def status_roundtrip():
            target = next(label for code, label in STATUS_LABELS.items() if code != original.status and code in (2, 3))
            c.edit("Status", target)
            r = c.sync()
            assert r.pushed == 1 and r.errors == 0, f"pushed={r.pushed} errors={r.errors} rejected={r.rejected}"
            assert c.api().status_label() == target, f"API status is {c.api().status_label()}"
            c.edit("Status", original.status_label())
            c.sync()
            assert c.api().status == original.status

        c.run("status: change and restore", status_roundtrip)

        def engineer_roundtrip():
            others = [a for a in roster.engineers if a.id != original.engineer_id]
            assert others, "no second engineer on the roster"
            c.edit("Engineer", others[0].name)
            r = c.sync()
            assert r.pushed == 1 and r.errors == 0, f"pushed={r.pushed} errors={r.errors} rejected={r.rejected}"
            assert c.api().engineer_id == others[0].id, f"engineer_id is {c.api().engineer_id}"
            c.edit("Engineer", roster.engineer_name(original.engineer_id) if original.engineer_id else "")
            c.sync()
            assert c.api().engineer_id == original.engineer_id, f"engineer_id not restored: {c.api().engineer_id}"

        c.run("engineer: reassign and restore", engineer_roundtrip)

        def unassign():
            c.edit("Engineer", "")
            r = c.sync()
            assert r.errors == 0, f"push errors: {r.errors}"
            if c.api().engineer_id is None:
                print("      the API clears engineer_id with null")
            else:
                assert r.rejected == 1, "the API ignored the clear and the engine did not notice"
                assert c.sheet_value("Engineer") == roster.engineer_name(original.engineer_id), "the sheet kept a value the API refused"
                print("      the API cannot unassign an engineer; the edit was refused cleanly and the sheet shows the truth")
            c.edit("Engineer", roster.engineer_name(original.engineer_id) if original.engineer_id else "")
            c.sync()

        c.run("engineer: clearing is applied, or refused cleanly if the API cannot", unassign)

        def both_sides_different_fields():
            new_status = 3 if original.status != 3 else 2
            c.client.update_ticket(ticket_id, {"status": new_status})  # the server moves...
            c.edit("Work Report", URL_B)  # ...while a human edits another field
            r = c.sync()
            assert r.conflicts == 0, f"unexpected conflicts: {r.conflicts}"
            now = c.api()
            assert now.status == new_status, "the fresh server status was overwritten"
            assert now.work_report == URL_B, "the sheet edit was lost"
            assert c.sheet_value("Status") == STATUS_LABELS[new_status]

        c.run("both sides at once, different fields: both survive", both_sides_different_fields)

        def both_sides_same_field():
            c.client.update_ticket(ticket_id, {"invoice": URL_B})  # server
            c.edit("Invoice", URL_C)  # human, same field
            r = c.sync()
            assert r.conflicts == 1, f"expected 1 conflict, got {r.conflicts}"
            assert c.api().invoice == URL_B, "the API value should have won"
            assert c.sheet_value("Invoice") == URL_B, "the sheet should now show the API value"
            logged = c.engine.backend.read_table(board.CONFLICTS)
            assert any(row.get("Sheet Value") == URL_C for row in logged), "the losing value was not logged"

        c.run("both sides at once, same field: API wins and the loser is logged", both_sides_same_field)
    finally:
        restore = {"status": original.status, "engineer_id": original.engineer_id}
        for name in ("invoice", "work_report"):
            restore[name] = None if name in original.null_fields else getattr(original, name)
        try:
            c.client.update_ticket(ticket_id, {k: v for k, v in restore.items() if k in touched})
            for name in ("invoice", "work_report"):  # a blank the API ignored: try the other spelling
                if getattr(c.api(), name).strip() != getattr(original, name):
                    c.client.update_ticket(ticket_id, {name: "" if restore[name] is None else None})
            c.sync()
            now = c.api()
            ok = (
                now.status == original.status
                and now.engineer_id == original.engineer_id
                and now.invoice.strip() == original.invoice
                and now.work_report.strip() == original.work_report
            )
            c.results.append(("restore: ticket is back to its original values", ok, "" if ok else "values differ, restore by hand"))
            print(("PASS  " if ok else "FAIL  ") + "restore: ticket is back to its original values")
        except ApiError as exc:
            c.results.append(("restore", False, str(exc)))
            print(f"FAIL  restore: {exc}  (fix ticket #{ticket_id} by hand!)")
    return c.results


def board_roster(engine: SyncEngine):
    from ..roster import Roster

    return Roster(engine.client.agents())


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Temporarily modify ONE ticket on the real API to verify the write path, then restore it.")
    parser.add_argument("--yes", action="store_true", help="confirm that modifying (and restoring) a ticket is allowed")
    parser.add_argument("--ticket", type=int, help="ticket id to use (default: an open ticket with an engineer and a manager)")
    args = parser.parse_args(argv)
    if not args.yes:
        print("This changes one ticket on the API and puts it back. Re-run with --yes to confirm.", file=sys.stderr)
        return 2
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    settings = Settings.from_env()
    engine = build_engine(settings)
    engine.run("full")
    results = run_checks(engine, pick_ticket(engine, args.ticket))
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
