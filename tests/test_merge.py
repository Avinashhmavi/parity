from fieldserve_board.merge import merge_ticket

F = ["status", "manager"]


def m(base, sheet, api, policy="api"):
    return merge_ticket(1, base, sheet, api, F, policy)


def test_unchanged_sheet_never_overwrites_fresh_api_change():
    r = m({"status": "Open", "manager": "A"}, {"status": "Open", "manager": "A"}, {"status": "Closed", "manager": "A"})
    assert r.values["status"] == "Closed" and not r.push and r.from_api == ["status"]


def test_sheet_edit_is_pushed_when_api_is_unchanged():
    r = m({"status": "Open", "manager": "A"}, {"status": "Open", "manager": "B"}, {"status": "Open", "manager": "A"})
    assert r.push == {"manager": "B"} and r.values["manager"] == "B" and not r.conflicts


def test_edits_to_different_fields_both_survive():
    r = m({"status": "Open", "manager": "A"}, {"status": "Open", "manager": "B"}, {"status": "Closed", "manager": "A"})
    assert r.values == {"status": "Closed", "manager": "B"}
    assert r.push == {"manager": "B"} and not r.conflicts


def test_same_field_changed_both_sides_api_wins_and_is_logged():
    r = m({"status": "Open", "manager": "A"}, {"status": "Pending", "manager": "A"}, {"status": "Closed", "manager": "A"})
    assert r.values["status"] == "Closed" and not r.push
    (c,) = r.conflicts
    assert (c.field, c.base, c.sheet, c.api, c.winner) == ("status", "Open", "Pending", "Closed", "api")


def test_sheet_policy_pushes_the_sheet_value():
    r = m({"status": "Open", "manager": "A"}, {"status": "Pending", "manager": "A"}, {"status": "Closed", "manager": "A"}, "sheet")
    assert r.push == {"status": "Pending"} and r.conflicts[0].winner == "sheet"


def test_both_sides_made_the_same_change_is_not_a_conflict():
    r = m({"status": "Open", "manager": "A"}, {"status": "Closed", "manager": "A"}, {"status": "Closed", "manager": "A"})
    assert not r.conflicts and not r.push


def test_no_baseline_means_api_wins_and_the_difference_is_logged():
    r = m(None, {"status": "Pending", "manager": "A"}, {"status": "Open", "manager": "A"})
    assert r.values["status"] == "Open" and r.conflicts[0].reason == "no baseline for this ticket"


def test_new_ticket_without_a_row_just_takes_the_api():
    r = m(None, None, {"status": "Open", "manager": "A"})
    assert r.values == {"status": "Open", "manager": "A"} and not r.conflicts and not r.push


def test_comparison_key_ignores_case_so_retyping_a_name_is_not_an_edit():
    key = lambda _f, v: v.casefold()  # noqa: E731
    r = merge_ticket(1, {"manager": "A b"}, {"manager": "a B"}, {"manager": "A b"}, ["manager"], "api", key)
    assert not r.push and not r.conflicts
