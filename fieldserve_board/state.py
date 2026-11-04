"""The sync baseline: what each ticket looked like when both sides last agreed.

Two-way sync cannot be done from two snapshots alone. Given a sheet value and
an API value that differ, you cannot tell *who changed*. The baseline (the
last value both sides agreed on) answers that, per field:

* sheet == baseline, API != baseline -> the API changed; take the API.
* API == baseline, sheet != baseline -> a human edited; push the sheet.
* both differ from baseline          -> conflict; see :mod:`merge`.

Stored as JSON, written atomically (temp file + rename) so a crash mid-write
cannot corrupt it.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

SCHEMA_VERSION = 1
MAX_CONFLICTS = 1000
MAX_ACTIVITY = 500


@dataclass
class State:
    baseline: Dict[str, Dict[str, str]] = field(default_factory=dict)  # ticket id -> field -> value
    checkpoint: str = ""  # max API updated_at seen, for incremental syncs
    last_sync: Dict[str, Any] = field(default_factory=dict)
    conflicts: List[Dict[str, Any]] = field(default_factory=list)
    activity: List[Dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "version": SCHEMA_VERSION,
            "baseline": self.baseline,
            "checkpoint": self.checkpoint,
            "last_sync": self.last_sync,
            "conflicts": self.conflicts[-MAX_CONFLICTS:],
            "activity": self.activity[-MAX_ACTIVITY:],
        }


class StateStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> State:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return State()
        except (OSError, ValueError):
            # A corrupt baseline must not crash the sync, but it must not be
            # silently trusted either. Keep the bad file for inspection and
            # start fresh: with no baseline the merge treats the API as truth.
            backup = self.path.with_suffix(self.path.suffix + ".corrupt")
            with contextlib.suppress(OSError):
                os.replace(self.path, backup)
            return State()
        if raw.get("version") != SCHEMA_VERSION:
            return State()
        return State(
            baseline={str(k): dict(v) for k, v in raw.get("baseline", {}).items()},
            checkpoint=raw.get("checkpoint", ""),
            last_sync=raw.get("last_sync", {}),
            conflicts=raw.get("conflicts", []),
            activity=raw.get("activity", []),
        )

    def save(self, state: State) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".state-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state.to_json(), handle, indent=1, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
