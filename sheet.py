#!/usr/bin/env python3
"""Export the ticket board to CSV, or type edits into it, without opening Excel."""

import sys

from fieldserve_board.cli import sheet_main

if __name__ == "__main__":
    sys.exit(sheet_main())
