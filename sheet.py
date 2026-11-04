#!/usr/bin/env python3
"""Export the ticket board to CSV, or type edits into it, without opening Excel."""

import sys

try:
    from fieldserve_board.cli import sheet_main
except ImportError as exc:  # a missing third-party package, not a bug in this repo
    sys.exit(f"missing dependency ({exc.name}). Install with:  python3 -m pip install -r requirements.txt")

if __name__ == "__main__":
    sys.exit(sheet_main())
