#!/usr/bin/env python3
"""Run one full two-way sync between the FieldServe API and the ticket board."""

import sys

try:
    from fieldserve_board.cli import sync_main
except ImportError as exc:  # a missing third-party package, not a bug in this repo
    sys.exit(f"missing dependency ({exc.name}). Install with:  python3 -m pip install -r requirements.txt")

if __name__ == "__main__":
    sys.exit(sync_main())
