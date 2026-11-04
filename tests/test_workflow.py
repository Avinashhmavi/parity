import pytest

from fieldserve_board.models import Agent
from fieldserve_board.roster import Roster
from fieldserve_board.workflow import DocState, StepStatus, TicketView, classify_document, evaluate

ROSTER = Roster(
    [
        Agent(1, "Zed Coordinator", "Coordinator"),
        Agent(2, "Amy Coordinator", "Coordinator"),
        Agent(3, "Mara Manager", "Manager"),
        Agent(5, "Eli Engineer", "Engineer"),
        Agent(9, "Fin Finance", "Finance"),
    ]
)
URL = "https://files.example/doc.pdf"


def view(**kw):
    base = dict(id=105, status="Open", engineer="", manager="", purchase_order="", delivery_note="", work_report="", invoice="")
    base.update(kw)
    return TicketView(**base)


@pytest.mark.parametrize(
    "value,state",
    [
        (URL, DocState.URL),
        ("http://a.example/x", DocState.URL),
        ("", DocState.EMPTY),
        (None, DocState.EMPTY),
        ("   ", DocState.EMPTY),
        ("NA", DocState.WAIVED),
        ("done", DocState.JUNK),
        ("asked Ravi", DocState.JUNK),
        ("ok", DocState.JUNK),
        ("na", DocState.JUNK),
        ("N/A", DocState.JUNK),
        ("ftp://files.example/x", DocState.JUNK),
        ("https://", DocState.JUNK),
        ("https://ok", DocState.JUNK),
        ("see https://a.example/x", DocState.JUNK),
    ],
)
def test_classify_document(value, state):
    assert classify_document(value) is state


def test_brief_example_ticket_105_waits_on_finance_for_delivery_note():
    ev = evaluate(view(manager="Mara Manager", engineer="Eli Engineer", purchase_order=URL), ROSTER)
    assert ev.stage == "Delivery Note"
    assert ev.action_owner == "Fin Finance"
    assert [s.status for s in ev.steps] == [
        StepStatus.COMPLETE,
        StepStatus.COMPLETE,
        StepStatus.COMPLETE,
        StepStatus.PENDING,
        StepStatus.UPCOMING,
        StepStatus.UPCOMING,
    ]


def test_first_unmet_step_wins_even_if_later_documents_exist():
    ev = evaluate(view(manager="Mara Manager", engineer="Eli Engineer", work_report=URL, invoice=URL), ROSTER)
    assert ev.stage == "Purchase Order"
    assert ev.action_owner == "Mara Manager"


@pytest.mark.parametrize("ticket_id,owner", [(100, "Amy Coordinator"), (101, "Zed Coordinator"), (102, "Amy Coordinator")])
def test_coordinator_is_chosen_by_id_parity_over_names_sorted(ticket_id, owner):
    ev = evaluate(view(id=ticket_id), ROSTER)
    assert ev.stage == "Assign Manager"
    assert ev.action_owner == owner


def test_assign_engineer_belongs_to_the_ticket_manager():
    ev = evaluate(view(manager="mara  manager"), ROSTER)
    assert (ev.stage, ev.action_owner) == ("Assign Engineer", "Mara Manager")


def test_work_report_belongs_to_the_engineer():
    ev = evaluate(view(manager="Mara Manager", engineer="Eli Engineer", purchase_order=URL, delivery_note="NA"), ROSTER)
    assert (ev.stage, ev.action_owner) == ("Work Report", "Eli Engineer")


def test_everything_done():
    ev = evaluate(
        view(status="Closed", manager="Mara Manager", engineer="Eli Engineer", purchase_order=URL, delivery_note="NA", work_report=URL, invoice="NA"),
        ROSTER,
    )
    assert (ev.stage, ev.action_owner, ev.flags) == ("Done", "", [])


@pytest.mark.parametrize(
    "doc,value,stage",
    [
        ("purchase_order", "NA", "Purchase Order"),  # PO is not waivable
        ("delivery_note", "NA", "Done"),  # DN waivable
        ("work_report", "NA", "Work Report"),  # WR never waivable
        ("invoice", "NA", "Done"),  # invoice waivable
        ("delivery_note", "done", "Delivery Note"),  # junk is not a document
    ],
)
def test_waiver_rules(doc, value, stage):
    docs = dict(purchase_order=URL, delivery_note=URL, work_report=URL, invoice=URL)
    docs[doc] = value
    ev = evaluate(view(manager="Mara Manager", engineer="Eli Engineer", **docs), ROSTER)
    assert ev.stage == stage


def test_closed_with_missing_paperwork_is_flagged():
    ev = evaluate(view(status="Closed", manager="Mara Manager", engineer="Eli Engineer", purchase_order=URL), ROSTER)
    assert "Closed but waiting on Delivery Note" in ev.flags


def test_resolved_without_work_report_is_flagged_even_with_junk_report():
    ev = evaluate(view(status="Resolved", manager="Mara Manager", engineer="Eli Engineer", work_report="done"), ROSTER)
    assert "Resolved without Work Report" in ev.flags
    assert "Work Report is not a link" in ev.flags


def test_resolved_with_work_report_is_not_flagged():
    ev = evaluate(view(status="Resolved", manager="Mara Manager", engineer="Eli Engineer", work_report=URL), ROSTER)
    assert "Resolved without Work Report" not in ev.flags


def test_manager_not_on_roster_is_flagged_but_step_is_met():
    ev = evaluate(view(manager="Somebody Else"), ROSTER)
    assert ev.stage == "Assign Engineer"
    assert ev.action_owner == "Somebody Else"
    assert "Manager not on roster" in ev.flags


def test_engineer_id_missing_from_roster_still_counts_as_assigned():
    ev = evaluate(view(manager="Mara Manager", engineer="#77"), ROSTER)
    assert ev.stage == "Purchase Order"
    assert "Engineer not on roster" in ev.flags
