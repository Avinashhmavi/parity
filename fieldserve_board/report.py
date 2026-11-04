"""A compact data-quality report over the board, for tuning heuristics on real data.

Prints counts and *samples*, never the whole dataset, so it is safe to paste
into a chat or a ticket. Run it after a sync:

    python3 sheet.py report
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Dict, Iterable, List, Mapping

from . import board
from .extract import email_domain
from .workflow import DocState, classify_document

_CODE_TOKEN = re.compile(r"\b(?=[A-Z0-9]*\d)(?=[A-Z0-9]*[A-Z])[A-Z0-9]{6}\b")
_DIGITS = re.compile(r"\d+")


def subject_shape(subject: str) -> str:
    """Mask the variable parts of a subject so templates group together."""
    text = _CODE_TOKEN.sub("<CODE>", (subject or "").upper())
    text = _DIGITS.sub("#", text)
    return " ".join(text.split())[:70]


def _top(counter: Counter, n: int) -> List[str]:
    return [f"  {count:>5}  {key}" for key, count in counter.most_common(n)]


def build_report(rows: Iterable[Mapping[str, str]], noise_rows: Iterable[Mapping[str, str]] = (), sample: int = 25) -> str:
    rows = list(rows)
    noise_rows = list(noise_rows)
    out: List[str] = []
    add = out.append

    add(f"TICKETS on board: {len(rows)}   in Noise sheet: {len(noise_rows)}")
    add("")
    add("Status:        " + ", ".join(f"{k or '(blank)'}={v}" for k, v in Counter(r.get("Status", "") for r in rows).most_common()))
    add("Stage:         " + ", ".join(f"{k}={v}" for k, v in Counter(r.get("Stage", "") for r in rows).most_common()))
    add("Job type:      " + ", ".join(f"{k}={v}" for k, v in Counter(r.get("Job Type", "") for r in rows).most_common()))
    no_store = [r for r in rows if not r.get("Store Code")]
    add(f"No store code: {len(no_store)}   (store code found: {len(rows) - len(no_store)})")
    flagged = Counter()
    for r in rows:
        for flag in filter(None, (f.strip() for f in r.get("Integrity", "").split(";"))):
            flagged[re.sub(r"waiting on .*", "waiting on <stage>", flag)] += 1
    add("")
    add("Integrity flags:")
    out.extend(_top(flagged, 12) or ["  (none)"])

    add("")
    add("Requester email domains:")
    out.extend(_top(Counter(email_domain(r.get("Requester", "")) or "(none)" for r in rows), 10))
    add("Requester local-part shapes (store codes masked):")
    shapes = Counter()
    for r in rows:
        local = (r.get("Requester", "").split("@", 1)[0]) or "(none)"
        shapes[_CODE_TOKEN.sub("<CODE>", local.upper()).lower()] += 1
    out.extend(_top(shapes, 12))

    add("")
    add("Most common subject shapes (digits -> #, store codes -> <CODE>):")
    out.extend(_top(Counter(subject_shape(r.get("Subject", "")) for r in rows), 15))

    add("")
    add(f"Sample of tickets with NO store code (up to {sample}):")
    for r in no_store[:sample]:
        add(f"  #{r.get('Ticket ID')}  {r.get('Subject', '')[:70]!r}  <{r.get('Requester', '')}>")
    if not no_store:
        add("  (none)")

    add("")
    add("Documents (valid link / waived / empty / junk):")
    for column in ("Purchase Order", "Delivery Note", "Work Report", "Invoice"):
        states = Counter(classify_document(r.get(column, "")).value for r in rows)
        add(f"  {column:<15} " + "  ".join(f"{s.value}={states.get(s.value, 0)}" for s in DocState))
    junk = Counter(
        r.get(c, "").strip()
        for r in rows
        for c in ("Purchase Order", "Delivery Note", "Work Report", "Invoice")
        if classify_document(r.get(c, "")) is DocState.JUNK
    )
    add("Most common junk values:")
    out.extend(_top(junk, 12) or ["  (none)"])

    if noise_rows:
        add("")
        add(f"Noise sheet (up to {sample}):")
        for r in noise_rows[:sample]:
            add(f"  #{r.get('Ticket ID')}  {r.get('Subject', '')[:60]!r}  <{r.get('Requester', '')}>  -> {r.get('Reason', '')}")
    return "\n".join(out)


def report_for_backend(backend, sample: int = 25) -> str:
    return build_report(backend.read_table(board.TICKETS), backend.read_table(board.NOISE), sample)


def counts(rows: Iterable[Mapping[str, str]]) -> Dict[str, int]:
    return dict(Counter(r.get("Stage", "") for r in rows))
