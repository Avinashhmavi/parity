"""Command-line entry points behind the root ``sync.py`` and ``sheet.py``."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from typing import List, Optional, Sequence

from . import board
from .backends import make_backend
from .client import ApiError
from .config import ConfigError, Settings
from .engine import build_engine
from .locking import LockTimeout, file_lock
from .roster import Roster
from .summary import workload


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)


# --------------------------------------------------------------------------
# sync.py
# --------------------------------------------------------------------------


def sync_main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="sync.py", description="Run one full two-way sync cycle and exit.")
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="only list tickets updated since the last checkpoint (fewer requests; the default is a full listing)",
    )
    parser.add_argument("--probe", action="store_true", help="print the API's response shapes and exit; changes nothing")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    try:
        settings = Settings.from_env()
        engine = build_engine(settings)
        if args.probe:
            return _probe(engine)
        result = engine.run("incremental" if args.incremental else "full")
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    except LockTimeout as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except ApiError as exc:
        print(f"API error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        logging.getLogger(__name__).exception("sync failed")
        print(f"sync failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result.as_dict()))
    return 0


def _probe(engine) -> int:
    """Show what the API actually returns, to verify the parsing assumptions."""
    client = engine.client
    agents = client._request("GET", "/api/v2/agents")
    tickets = client._request("GET", "/api/v2/tickets", params={"per_page": 2})
    print(json.dumps({"agents": agents, "tickets": tickets}, indent=2, default=str)[:6000])
    return 0


# --------------------------------------------------------------------------
# sheet.py
# --------------------------------------------------------------------------


def export_csv(backend, out_path: str) -> int:
    rows = backend.read_table(board.TICKETS)
    headers = list(rows[0].keys()) if rows else list(board.TICKET_COLUMNS)
    with open(out_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(headers)
        for row in rows:
            writer.writerow([row.get(h, "") for h in headers])
    return len(rows)


def read_edits(path: str) -> List[board.Edit]:
    edits: List[board.Edit] = []
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = {"Ticket ID", "Column", "Value"} - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"edits file needs columns Ticket ID,Column,Value (missing: {', '.join(sorted(missing))})")
        for line, record in enumerate(reader, start=2):
            ticket_id = board.parse_ticket_id(record["Ticket ID"])
            if ticket_id is None:
                raise ValueError(f"line {line}: bad Ticket ID {record['Ticket ID']!r}")
            edits.append((ticket_id, record["Column"].strip(), record["Value"] or ""))
    return edits


def apply_edits(backend, edits: Sequence[board.Edit]) -> List[str]:
    """Write cells like a human, then refresh the computed columns locally.

    No API call happens here; the next sync decides what an edit means.
    """
    roster = Roster.from_sheet_rows(backend.read_table(board.ROSTER))
    problems = backend.edit_cells(list(edits))

    touched = {e[0] for e in edits}
    rows = [r for r in backend.read_table(board.TICKETS) if board.parse_ticket_id(r.get("Ticket ID", "")) in touched]
    problems += backend.edit_cells(board.derived_edits(rows, roster))
    return problems


def sheet_main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="sheet.py", description="Drive the ticket board without opening Excel.")
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export", help="write the Tickets sheet to a CSV file")
    export.add_argument("path")
    apply = sub.add_parser("apply", help="type values into cells from a 'Ticket ID,Column,Value' CSV; never syncs")
    apply.add_argument("path")
    sub.add_parser("summary", help="print how many tickets are waiting on each person")
    sub.add_parser("report", help="print a compact data-quality report (counts and samples) to tune heuristics")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    try:
        settings = Settings.from_env(require_key=False)
        backend = make_backend(settings)
        with file_lock(settings.state_path.with_suffix(".lock")):
            if args.command == "export":
                count = export_csv(backend, args.path)
                print(f"exported {count} tickets to {args.path}")
                return 0
            if args.command == "apply":
                edits = read_edits(args.path)
                problems = apply_edits(backend, edits)
                print(f"applied {len(edits)} edit(s)")
                for problem in problems:
                    print(f"warning: {problem}", file=sys.stderr)
                return 2 if problems else 0
            if args.command == "report":
                from .report import report_for_backend

                print(report_for_backend(backend))
                return 0
            rows = backend.read_table(board.TICKETS)
            roster = Roster.from_sheet_rows(backend.read_table(board.ROSTER))
            for entry in workload(rows, roster):
                print(f"{entry['pending']:>5}  {entry['person']} ({entry['role']})")
            return 0
    except (ConfigError, FileNotFoundError, KeyError, ValueError, LockTimeout) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
