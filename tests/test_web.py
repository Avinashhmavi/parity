from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from fieldserve_board.backends import XlsxBackend
from fieldserve_board.state import StateStore
from fieldserve_board.web.app import create_app
from fieldserve_board.web.service import BoardService


@pytest.fixture()
def client(rig):
    rig.sync()
    service = BoardService(rig.settings, rig.backend, rig.store, rig.engine)
    with TestClient(create_app(service=service)) as c:
        c.rig = rig
        yield c


def wait_idle(client, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not client.get("/api/sync").json()["syncing"]:
            return
        time.sleep(0.05)
    raise AssertionError("sync did not finish")


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["canSync"] and body["lastSync"]["ok"]


def test_board_paging_filtering_sorting(client):
    full = client.get("/api/board", params={"pageSize": 10}).json()
    assert len(full["items"]) == 10 and full["total"] > 10
    stage = full["items"][0]["stage"]
    only = client.get("/api/board", params={"stage": stage, "pageSize": 200}).json()
    assert only["total"] > 0 and {i["stage"] for i in only["items"]} == {stage}
    flagged = client.get("/api/board", params={"flagged": True, "pageSize": 200}).json()
    assert all(i["integrity"] for i in flagged["items"])
    desc = client.get("/api/board", params={"sort": "id", "order": "desc", "pageSize": 5}).json()["items"]
    assert [i["id"] for i in desc] == sorted((i["id"] for i in desc), reverse=True)
    needle = full["items"][2]["subject"].split()[0]
    assert client.get("/api/board", params={"q": needle}).json()["total"] >= 1
    assert client.get("/api/board", params={"pageSize": 1000}).status_code == 422


def test_ticket_detail_has_steps_in_order_and_options(client):
    item = client.get("/api/tickets/101").json()
    assert [s["key"] for s in item["steps"]] == ["manager", "engineer", "purchase_order", "delivery_note", "work_report", "invoice"]
    pending = [s for s in item["steps"] if s["status"] == "pending"]
    assert len(pending) <= 1 and (pending[0]["label"] == item["stage"] if pending else item["stage"] == "Done")
    assert "Chitra Menon" in item["options"]["managers"]


def test_unknown_ticket_is_404(client):
    assert client.get("/api/tickets/424242").status_code == 404


def test_summary_counts_add_up(client):
    s = client.get("/api/summary").json()
    pending_by_person = sum(p["pending"] for p in s["workload"])
    assert pending_by_person == s["totals"]["pending"]
    assert s["totals"]["tickets"] == s["totals"]["pending"] + s["totals"]["done"]
    assert list(s["stages"])[0] == "Assign Manager" and list(s["stages"])[-1] == "Done"


def test_edit_validates_then_writes_the_sheet_and_flags_it_unsynced(client):
    bad = client.patch("/api/tickets/101", json={"engineer": "Nobody"})
    assert bad.status_code == 422 and "Engineer" in bad.json()["detail"]
    assert client.patch("/api/tickets/101", json={"subject": "x"}).status_code == 422  # not editable
    ok = client.patch("/api/tickets/101", json={"manager": "Dev Malhotra"})
    assert ok.status_code == 200 and ok.json()["manager"] == "Dev Malhotra"
    assert "Manager" in ok.json()["unsynced"]
    assert client.rig.api.ticket(101)["manager"] != "Dev Malhotra"  # nothing pushed until a sync


def test_edit_then_sync_pushes_to_the_api(client):
    client.patch("/api/tickets/101", json={"manager": "Dev Malhotra"})
    assert client.post("/api/sync").status_code == 202
    wait_idle(client)
    assert client.rig.api.ticket(101)["manager"] == "Dev Malhotra"
    assert client.get("/api/tickets/101").json()["unsynced"] == []


def test_second_sync_while_running_is_refused(client):
    client.rig.api.state.rate_limit = 100000
    first = client.post("/api/sync")
    second = client.post("/api/sync")
    assert first.status_code == 202 and second.status_code == 409
    wait_idle(client)


def test_websocket_announces_sync(client):
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "hello"
        client.post("/api/sync")
        seen = set()
        while "sync.finished" not in seen:
            seen.add(ws.receive_json()["type"])
        assert "sync.started" in seen


def test_read_only_without_api_key(rig):
    rig.sync()
    service = BoardService(rig.settings, XlsxBackend(rig.xlsx), StateStore(rig.settings.state_path), engine=None)
    with TestClient(create_app(service=service)) as c:
        assert c.get("/api/health").json()["canSync"] is False
        assert c.post("/api/sync").status_code == 409
        assert c.get("/api/board").status_code == 200


def test_noise_conflicts_activity_endpoints(client):
    assert isinstance(client.get("/api/noise").json(), list)
    assert isinstance(client.get("/api/conflicts").json(), list)
    assert client.get("/api/activity").json()[0]["kind"] in {"added", "ignored", "warning", "removed"}


# ---- access control ---------------------------------------------------------


def _locked(rig, **extra):
    from fieldserve_board.config import Settings

    settings = Settings.from_env(
        {
            "FIELDOPS_BASE_URL": rig.settings.base_url,
            "FIELDOPS_API_KEY": "fk_test",
            "BOARD_XLSX_PATH": str(rig.xlsx),
            "BOARD_STATE_PATH": str(rig.settings.state_path),
            "BOARD_PASSWORD": "s3cret pass",
            "BOARD_USER": "ops",
            **extra,
        }
    )
    rig.sync()
    service = BoardService(settings, rig.backend, rig.store, rig.engine)
    return TestClient(create_app(service=service))


def test_password_protects_api_ui_and_websocket(rig):
    import base64

    good = {"Authorization": "Basic " + base64.b64encode(b"ops:s3cret pass").decode()}
    bad = {"Authorization": "Basic " + base64.b64encode(b"ops:wrong").decode()}
    with _locked(rig) as c:
        assert c.get("/api/live").json() == {"status": "ok"}  # liveness stays open
        for path in ("/api/board", "/api/summary", "/api/health", "/api/tickets/101"):
            r = c.get(path)
            assert r.status_code == 401 and "Basic" in r.headers["www-authenticate"], path
            assert c.get(path, headers=bad).status_code == 401
            assert c.get(path, headers=good).status_code == 200, path
        assert c.patch("/api/tickets/101", json={"manager": "Dev Malhotra"}).status_code == 401
        assert c.post("/api/sync").status_code == 401
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect), c.websocket_connect("/ws"):
            pass
        with c.websocket_connect("/ws", headers=good) as ws:
            assert ws.receive_json()["type"] == "hello"


def test_garbage_authorization_headers_are_rejected_not_crashed(rig):
    with _locked(rig) as c:
        for header in ("Basic", "Basic !!!notbase64", "Bearer abc", "Basic " + "A" * 10):
            assert c.get("/api/board", headers={"Authorization": header}).status_code == 401
