"""The Google backend against an in-memory fake of gspread.

Not a test of Google itself (no credentials in CI): it proves the backend
honours the same contract as Excel by running the real sync engine through it.
"""

from __future__ import annotations

import gspread
import pytest

from fieldserve_board import board
from fieldserve_board.backends import gsheets
from fieldserve_board.backends.gsheets import GoogleSheetsBackend
from fieldserve_board.engine import SyncEngine
from fieldserve_board.state import StateStore


class FakeWorksheet:
    def __init__(self, title, rows=100):
        self.title = title
        self.values = []
        self.row_count = rows

    def get_all_values(self):
        return [list(r) for r in self.values]

    def clear(self):
        self.values = []

    def resize(self, rows=None, cols=None):
        self.row_count = rows or self.row_count

    def update(self, values, cell, value_input_option=None):
        assert cell == "A1" and value_input_option == "RAW"
        self.values = [[str(c) for c in row] for row in values]

    def freeze(self, rows=0, cols=0):
        pass

    def format(self, rng, fmt):
        pass

    def batch_update(self, updates, value_input_option=None):
        for u in updates:
            a1 = u["range"]
            col = 0
            i = 0
            while a1[i].isalpha():
                col = col * 26 + (ord(a1[i]) - 64)
                i += 1
            row = int(a1[i:])
            while len(self.values) < row:
                self.values.append([])
            line = self.values[row - 1]
            while len(line) < col:
                line.append("")
            line[col - 1] = u["values"][0][0]


class FakeBook:
    def __init__(self):
        self.sheets = {}

    def worksheet(self, name):
        if name not in self.sheets:
            raise gspread.WorksheetNotFound(name)
        return self.sheets[name]

    def add_worksheet(self, title, rows, cols):
        self.sheets[title] = FakeWorksheet(title, rows)
        return self.sheets[title]


class FakeClient:
    def __init__(self, book):
        self.book = book

    def open_by_key(self, _key):
        return self.book


@pytest.fixture()
def gbackend(monkeypatch):
    book = FakeBook()
    monkeypatch.setattr(gspread, "service_account_from_dict", lambda info: FakeClient(book))
    return GoogleSheetsBackend("sheet-id", '{"type": "service_account"}')


def test_requires_configuration():
    with pytest.raises(ValueError):
        GoogleSheetsBackend("", "x")
    with pytest.raises(ValueError):
        GoogleSheetsBackend("id", "")


def test_full_sync_cycle_through_the_google_backend(api, tmp_path, gbackend):
    from tests.conftest import Rig

    rig = Rig(api, tmp_path)
    engine = SyncEngine(rig.client, gbackend, StateStore(tmp_path / "g-state.json"), rig.settings)
    first = engine.run()
    assert first.ok and first.operational > 0
    rows = {int(r["Ticket ID"]): r for r in gbackend.read_table(board.TICKETS)}
    assert len(rows) == first.operational

    tid = next(i for i, t in sorted(api.state.tickets.items()) if "OMNIMART" in t["subject"])
    problems = gbackend.edit_cells([(tid, "Invoice", "https://files.example/inv.pdf")])
    assert problems == []
    api.put(next(i for i in rows if i != tid), status=3)
    second = engine.run()
    assert second.pushed == 1
    assert api.ticket(tid)["invoice"] == "https://files.example/inv.pdf"
    assert engine.run().pushed == 0


def test_edit_cells_reports_unknown_ticket_and_column(gbackend):
    gbackend.write_tables({board.TICKETS: gsheets.Table(["Ticket ID", "Invoice"], [["1", ""]])})
    problems = gbackend.edit_cells([(2, "Invoice", "x"), (1, "Nope", "y")])
    assert len(problems) == 2
