from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from fieldserve_board.backends import XlsxBackend
from fieldserve_board.client import FieldServeClient
from fieldserve_board.config import Settings
from fieldserve_board.devtools.mock_api import MockState, create_app, seed_tickets
from fieldserve_board.engine import SyncEngine
from fieldserve_board.state import StateStore

KEY = "fk_test"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class MockServer:
    def __init__(self):
        self.state = MockState(api_key=KEY, rate_limit=100000)
        self.port = _free_port()
        config = uvicorn.Config(create_app(self.state), host="127.0.0.1", port=self.port, log_level="error")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> MockServer:
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                return self
            time.sleep(0.05)
        raise RuntimeError("mock server did not start")

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)

    def reset(self, count: int = 0) -> None:
        self.state.tickets.clear()
        self.state.hits.clear()
        self.state.rate_limit = 100000
        self.state.requests_total = 0
        self.state.rejected_429 = 0
        if count:
            seed_tickets(self.state, count)

    def put(self, ticket_id: int, **changes) -> None:
        with self.state.lock:
            self.state.tickets[ticket_id].update(changes)
            self.state.touch(self.state.tickets[ticket_id])

    def ticket(self, ticket_id: int) -> dict:
        return dict(self.state.tickets[ticket_id])


@pytest.fixture(scope="session")
def mock_server():
    server = MockServer().start()
    yield server
    server.stop()


@pytest.fixture()
def api(mock_server):
    mock_server.reset(count=60)
    return mock_server


class Rig:
    """A sync engine wired to the mock API and a temp workbook."""

    def __init__(self, api: MockServer, tmp_path: Path, policy: str = "api"):
        self.api = api
        self.tmp = tmp_path
        self.xlsx = tmp_path / "board.xlsx"
        self.settings = Settings.from_env(
            {
                "FIELDOPS_BASE_URL": api.url,
                "FIELDOPS_API_KEY": KEY,
                "BOARD_XLSX_PATH": str(self.xlsx),
                "BOARD_STATE_PATH": str(tmp_path / "state.json"),
                "API_REQUESTS_PER_MINUTE": "100000",
                "CONFLICT_POLICY": policy,
            }
        )
        self.backend = XlsxBackend(self.xlsx)
        self.store = StateStore(self.settings.state_path)
        self.client = FieldServeClient(api.url, KEY, requests_per_minute=100000, timeout=10)
        self.engine = SyncEngine(self.client, self.backend, self.store, self.settings)

    def sync(self, mode: str = "full"):
        return self.engine.run(mode)

    def rows(self) -> dict:
        from fieldserve_board import board

        return {int(r["Ticket ID"]): r for r in self.backend.read_table(board.TICKETS)}

    def edit(self, ticket_id: int, column: str, value: str) -> None:
        problems = self.backend.edit_cells([(ticket_id, column, value)])
        assert not problems, problems


@pytest.fixture()
def rig(api, tmp_path):
    return Rig(api, tmp_path)
