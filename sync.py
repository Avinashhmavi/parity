#!/usr/bin/env python3
"""Run one full two-way sync between the FieldServe API and the ticket board."""

import sys

from fieldserve_board.cli import sync_main

if __name__ == "__main__":
    sys.exit(sync_main())
