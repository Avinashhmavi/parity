"""The contract between the sync engine and a spreadsheet product.

Three operations are enough for both Excel and Google Sheets:

``read_table``   rows of one sheet as header-keyed dicts (column order and
                 extra columns are the user's business)
``write_tables`` replace whole sheets (the sync engine owns their content)
``edit_cells``   change individual Tickets cells, as a human would
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Tuple


@dataclass
class Table:
    headers: List[str]
    rows: List[List[str]] = field(default_factory=list)

    @classmethod
    def from_dicts(cls, headers: Sequence[str], rows: Sequence[dict]) -> Table:
        return cls(list(headers), [[_cell(r.get(h, "")) for h in headers] for r in rows])


def _cell(value: object) -> str:
    return "" if value is None else str(value)


class BoardBackend(ABC):
    name = "backend"

    @abstractmethod
    def read_table(self, name: str) -> List[Dict[str, str]]:
        """Rows of sheet ``name``; ``[]`` if it does not exist. Blank rows skipped."""

    @abstractmethod
    def write_tables(self, tables: Dict[str, Table]) -> None:
        """Replace the named sheets, creating them if needed. Others are left alone."""

    @abstractmethod
    def edit_cells(self, edits: Sequence[Tuple[int, str, str]]) -> List[str]:
        """Set ``(ticket id, column header) -> value`` on the Tickets sheet.

        Returns a list of problems (unknown ticket, unknown column); applies
        everything it can.
        """

    def describe(self) -> str:
        return self.name
