"""The live write check, pointed at the mock: it must pass and leave the ticket as it found it."""

from __future__ import annotations

from fieldserve_board.devtools import live_check
from fieldserve_board.engine import SyncEngine


def test_live_check_passes_and_restores_the_ticket(rig, capsys, monkeypatch):
    engine = SyncEngine(rig.client, rig.backend, rig.store, rig.settings)
    rig.sync()
    tid = live_check.pick_ticket(engine, None)
    before = rig.api.ticket(tid)

    results = live_check.run_checks(engine, tid)

    out = capsys.readouterr().out
    assert all(ok for _, ok, _ in results), out
    after = rig.api.ticket(tid)
    for key in ("status", "engineer_id", "invoice", "work_report", "manager", "purchase_order", "delivery_note"):
        assert after[key] == before[key], key


def test_refuses_to_write_without_confirmation(capsys):
    assert live_check.main([]) == 2
    assert "--yes" in capsys.readouterr().err
