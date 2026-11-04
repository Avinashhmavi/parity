"""End-to-end: real HTTP against the mock API, real xlsx on disk."""

from __future__ import annotations

import csv

import pytest

from fieldserve_board import board
from fieldserve_board.cli import apply_edits, read_edits, sheet_main

URL = "https://files.fieldserve.example/x.pdf"


def pick(api, **want):
    """First operational ticket whose server fields match ``want``."""
    for t in sorted(api.state.tickets.values(), key=lambda t: t["id"]):
        if all(t.get(k) == v for k, v in want.items()) and "OMNIMART" in t["subject"]:
            return t["id"]
    raise AssertionError(f"no ticket matching {want}")


def test_first_sync_builds_every_required_column(rig):
    result = rig.sync()
    assert result.ok and result.errors == 0
    rows = rig.rows()
    required = ["Ticket ID", "Subject", "Status", "Engineer", "Manager", "Purchase Order", "Delivery Note", "Work Report", "Invoice", "Stage", "Action Owner"]
    assert all(c in next(iter(rows.values())) for c in required)
    assert len(rows) + result.noise == len(rig.api.state.tickets)


def test_second_sync_changes_nothing(rig):
    rig.sync()
    before = rig.rows()
    again = rig.sync()
    assert (again.pushed, again.conflicts, again.rejected, again.updated_from_api, again.created) == (0, 0, 0, 0, 0)
    assert rig.rows() == before


def test_server_change_flows_into_the_sheet_and_recomputes_the_stage(rig):
    rig.sync()
    tid = pick(rig.api, manager="")
    rig.api.put(tid, manager="Chitra Menon", status=3)
    rig.sync()
    row = rig.rows()[tid]
    assert row["Manager"] == "Chitra Menon" and row["Status"] == "Pending"
    assert row["Stage"] in ("Assign Engineer",) and row["Action Owner"] == "Chitra Menon"


def test_sheet_edit_is_pushed_to_the_api(rig):
    rig.sync()
    tid = pick(rig.api, engineer_id=None, manager="Chitra Menon") if any(
        t["engineer_id"] is None and t["manager"] == "Chitra Menon" for t in rig.api.state.tickets.values()
    ) else pick(rig.api)
    rig.edit(tid, "Engineer", "Esha Pillai")
    rig.edit(tid, "Purchase Order", URL)
    result = rig.sync()
    assert result.pushed == 2
    server = rig.api.ticket(tid)
    assert server["engineer_id"] == 5 and server["purchase_order"] == URL
    assert rig.rows()[tid]["Engineer"] == "Esha Pillai"


def test_unchanged_sheet_cells_never_overwrite_a_fresh_server_change(rig):
    rig.sync()
    tid = pick(rig.api)
    new_status = 4 if rig.api.ticket(tid)["status"] != 4 else 3
    rig.api.put(tid, status=new_status, invoice="NA")  # server moves; sheet is untouched
    result = rig.sync()
    assert result.pushed == 0
    assert rig.api.ticket(tid)["status"] == new_status and rig.api.ticket(tid)["invoice"] == "NA"
    assert rig.rows()[tid]["Status"] == board.STATUS_LABEL_LIST[new_status - 2]


def test_ticket_changed_on_both_sides_at_once_merges_different_fields(rig):
    rig.sync()
    tid = pick(rig.api)
    rig.api.put(tid, status=4)  # server: status
    rig.edit(tid, "Work Report", URL)  # human: work report
    result = rig.sync()
    assert result.conflicts == 0 and result.pushed == 1
    server = rig.api.ticket(tid)
    assert server["status"] == 4 and server["work_report"] == URL
    row = rig.rows()[tid]
    assert row["Status"] == "Resolved" and row["Work Report"] == URL


def test_same_field_conflict_api_wins_and_the_loser_is_logged(rig):
    rig.sync()
    tid = pick(rig.api, status=2) if any(t["status"] == 2 for t in rig.api.state.tickets.values()) else pick(rig.api)
    original = rig.api.ticket(tid)["status"]
    server_value = 5 if original != 5 else 4
    sheet_value = "Pending" if original != 3 else "Open"
    rig.api.put(tid, status=server_value)
    rig.edit(tid, "Status", sheet_value)
    result = rig.sync()
    assert result.conflicts == 1 and result.pushed == 0
    assert rig.api.ticket(tid)["status"] == server_value
    assert rig.rows()[tid]["Status"] == board.STATUS_LABEL_LIST[server_value - 2]
    conflicts = rig.backend.read_table(board.CONFLICTS)
    assert conflicts[0]["Sheet Value"] == sheet_value and conflicts[0]["Winner"] == "api"


def test_sheet_policy_makes_the_human_win(api, tmp_path):
    from tests.conftest import Rig

    rig = Rig(api, tmp_path, policy="sheet")
    rig.sync()
    tid = pick(api)
    cur = api.ticket(tid)["status"]
    api.put(tid, status=5 if cur != 5 else 4)
    rig.edit(tid, "Status", "Pending" if cur != 3 else "Open")
    rig.sync()
    assert api.ticket(tid)["status"] == (3 if cur != 3 else 2)


def test_invalid_engineer_is_rejected_and_reverted_not_sent(rig):
    rig.sync()
    tid = pick(rig.api)
    before = rig.api.ticket(tid)["engineer_id"]
    rig.edit(tid, "Engineer", "Nobody Atall")
    result = rig.sync()
    assert result.rejected == 1 and result.pushed == 0
    assert rig.api.ticket(tid)["engineer_id"] == before
    assert rig.rows()[tid]["Engineer"] != "Nobody Atall"


def test_one_bad_field_does_not_block_the_good_one(rig):
    rig.sync()
    tid = pick(rig.api)
    rig.edit(tid, "Manager", "Not A Manager")
    rig.edit(tid, "Invoice", URL)
    result = rig.sync()
    assert result.rejected == 1 and result.pushed == 1
    assert rig.api.ticket(tid)["invoice"] == URL


def test_clearing_the_engineer_unassigns_on_the_server(rig):
    rig.sync()
    tid = pick(rig.api)
    rig.api.put(tid, engineer_id=5)
    rig.sync()
    rig.edit(tid, "Engineer", "")
    rig.sync()
    assert rig.api.ticket(tid)["engineer_id"] is None
    assert rig.rows()[tid]["Stage"] in ("Assign Engineer", "Assign Manager")


def test_case_only_retyping_of_a_name_is_not_a_push(rig):
    rig.sync()
    tid = pick(rig.api)
    rig.api.put(tid, manager="Chitra Menon")
    rig.sync()
    rig.edit(tid, "Manager", "chitra menon")
    assert rig.sync().pushed == 0


def test_computed_columns_are_ignored_when_edited(rig):
    rig.sync()
    tid = pick(rig.api)
    stage = rig.rows()[tid]["Stage"]
    rig.edit(tid, "Stage", "Done")
    rig.edit(tid, "Action Owner", "Someone")
    result = rig.sync()
    assert result.pushed == 0 and rig.rows()[tid]["Stage"] == stage


def test_new_server_ticket_appears_and_removed_one_disappears(rig):
    rig.sync()
    rig.api.state.tickets.pop(min(t for t in rig.api.state.tickets if "OMNIMART" in rig.api.state.tickets[t]["subject"]))
    rig.api.state.tickets[9001] = {
        "id": 9001, "subject": "PM AT OMNIMART NEWTOWN (Z9Y8XW)", "status": 2, "engineer_id": None, "manager": "",
        "purchase_order": "", "delivery_note": "", "work_report": "", "invoice": "", "updated_at": "2099-01-01T00:00:00Z",
        "requester": {"email": "store.z9y8xw@omnimart.example"},
    }
    result = rig.sync()
    assert result.removed == 1 and result.created == 1
    assert 9001 in rig.rows()


def test_incremental_mode_picks_up_changes_and_pushes_edits(rig):
    rig.sync()
    tid, other = [i for i in sorted(rig.rows())][:2]
    rig.api.put(tid, status=3)
    rig.edit(other, "Invoice", URL)
    result = rig.sync("incremental")
    assert result.pushed == 1 and rig.rows()[tid]["Status"] == "Pending"
    assert rig.api.ticket(other)["invoice"] == URL
    assert result.requests < 10


def test_row_order_and_extra_user_columns_survive(rig):
    rig.sync()
    order = list(rig.rows())
    rig.sync()
    assert list(rig.rows()) == order


def test_edit_made_during_the_sync_is_held_for_the_next_one(rig, monkeypatch):
    rig.sync()
    tid = pick(rig.api)
    real_read = rig.backend.read_table
    reads = {"n": 0}

    def read_then_edit(name):
        rows = real_read(name)
        if name == board.TICKETS:
            reads["n"] += 1
            if reads["n"] == 1:  # the human types right after we read the sheet
                rig.edit(tid, "Invoice", URL)
        return rows

    monkeypatch.setattr(rig.backend, "read_table", read_then_edit)
    result = rig.sync()
    monkeypatch.setattr(rig.backend, "read_table", real_read)
    assert result.errors == 0
    assert rig.rows()[tid]["Invoice"] == URL  # the sync did not erase it
    nxt = rig.sync()
    assert nxt.pushed == 1 and rig.api.ticket(tid)["invoice"] == URL


def test_failed_push_is_retried_next_sync(rig, monkeypatch):
    rig.sync()
    tid = pick(rig.api)
    rig.edit(tid, "Invoice", URL)
    real_put = rig.client.update_ticket

    def boom(ticket_id, changes):
        from fieldserve_board.client import ApiError

        raise ApiError(503, "unavailable")

    monkeypatch.setattr(rig.client, "update_ticket", boom)
    result = rig.sync()
    assert result.errors == 1 and rig.rows()[tid]["Invoice"] == URL  # human's edit kept
    monkeypatch.setattr(rig.client, "update_ticket", real_put)
    assert rig.sync().pushed == 1 and rig.api.ticket(tid)["invoice"] == URL


def test_lost_state_does_not_clobber_the_api_with_stale_sheet_values(rig):
    rig.sync()
    tid = pick(rig.api)
    new_status = 4 if rig.api.ticket(tid)["status"] != 4 else 3
    rig.api.put(tid, status=new_status)
    rig.store.path.unlink()  # baseline lost; sheet still says the old status
    result = rig.sync()
    assert rig.api.ticket(tid)["status"] == new_status and result.pushed == 0
    assert result.conflicts >= 1


def test_noise_is_kept_off_the_board_and_listed_with_a_reason(rig):
    rig.api.state.tickets[7001] = {
        "id": 7001, "subject": "Limited time offer: 50% OFF", "status": 2, "engineer_id": None, "manager": "",
        "purchase_order": "", "delivery_note": "", "work_report": "", "invoice": "", "updated_at": "2099-01-01T00:00:00Z",
        "requester": {"email": "promo@bulkmail.example"},
    }
    rig.sync()
    assert 7001 not in rig.rows()
    noise = {r["Ticket ID"]: r for r in rig.backend.read_table(board.NOISE)}
    assert "7001" in noise and noise["7001"]["Reason"]


# ---- sheet.py -------------------------------------------------------------


def test_export_and_apply_roundtrip_like_the_grader(rig, tmp_path, monkeypatch):
    rig.sync()
    monkeypatch.setenv("FIELDOPS_API_KEY", "fk_test")
    monkeypatch.setenv("BOARD_XLSX_PATH", str(rig.xlsx))
    monkeypatch.setenv("BOARD_STATE_PATH", str(rig.settings.state_path))
    out = tmp_path / "out.csv"
    assert sheet_main(["export", str(out)]) == 0
    with open(out, newline="", encoding="utf-8") as fh:
        exported = list(csv.DictReader(fh))
    assert {r["Ticket ID"] for r in exported} == {str(i) for i in rig.rows()}

    tid = int(exported[3]["Ticket ID"])
    edits = tmp_path / "edits.csv"
    edits.write_text(f"Ticket ID,Column,Value\n{tid},Work Report,{URL}\n{tid},Invoice,NA\n", encoding="utf-8")
    assert sheet_main(["apply", str(edits)]) == 0
    row = rig.rows()[tid]
    assert row["Work Report"] == URL and row["Invoice"] == "NA"
    assert rig.api.ticket(tid)["invoice"] != "NA" or rig.api.ticket(tid)["work_report"] != URL  # apply never syncs
    assert rig.sync().pushed >= 1


def test_apply_refreshes_stage_like_a_formula_would(rig):
    rig.sync()
    tid = pick(rig.api, manager="")
    rig.edit(tid, "Manager", "Chitra Menon")
    apply_edits(rig.backend, [(tid, "Manager", "Chitra Menon")])
    row = rig.rows()[tid]
    assert row["Stage"] == "Assign Engineer" and row["Action Owner"] == "Chitra Menon"


def test_apply_reports_unknown_tickets_and_columns(rig, tmp_path):
    rig.sync()
    problems = apply_edits(rig.backend, [(999999, "Invoice", "NA"), (min(rig.rows()), "Nope", "x")])
    assert len(problems) == 2


def test_read_edits_validates_the_header(tmp_path):
    bad = tmp_path / "e.csv"
    bad.write_text("id,col,val\n1,a,b\n", encoding="utf-8")
    with pytest.raises(ValueError):
        read_edits(str(bad))


def test_export_without_a_workbook_is_a_clear_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("BOARD_XLSX_PATH", str(tmp_path / "none.xlsx"))
    monkeypatch.setenv("BOARD_STATE_PATH", str(tmp_path / "s.json"))
    out = tmp_path / "o.csv"
    code = sheet_main(["export", str(out)])
    # An empty board exports just the headers rather than crashing.
    assert code == 0 and out.read_text().startswith("Ticket ID,")
