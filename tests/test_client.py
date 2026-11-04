from __future__ import annotations

import logging

import pytest

from fieldserve_board.client import ApiError, FieldServeClient, RateLimiter, parse_ticket
from fieldserve_board.devtools.mock_api import iso
from tests.conftest import KEY


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.slept = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def test_rate_limiter_spaces_requests_inside_the_window():
    clock = FakeClock()
    limiter = RateLimiter(3, 60.0, clock=clock.time, sleep=clock.sleep)
    for _ in range(3):
        limiter.acquire()
    assert clock.slept == []
    limiter.acquire()  # the 4th must wait for the first to age out
    assert sum(clock.slept) == pytest.approx(60.0, abs=0.5)


def test_rate_limiter_never_exceeds_the_limit_over_many_calls():
    clock = FakeClock()
    limiter = RateLimiter(5, 10.0, clock=clock.time, sleep=clock.sleep)
    stamps = []
    for _ in range(40):
        limiter.acquire()
        stamps.append(clock.now)
    for i, t in enumerate(stamps):
        in_window = [s for s in stamps if t - 10.0 < s <= t]
        assert len(in_window) <= 5, (i, in_window)


def test_list_all_walks_past_the_500_ticket_cap_without_asking_for_page_11(mock_server):
    mock_server.reset(count=1300)
    client = FieldServeClient(mock_server.url, KEY, requests_per_minute=100000)
    found = client.list_all()
    assert len(found) == 1300
    assert mock_server.state.rejected_429 == 0
    # Every listing request was legal: the mock answers 400 to page > 10,
    # which the client would have raised as ApiError.


def test_list_all_survives_a_whole_window_sharing_one_timestamp(mock_server, caplog):
    mock_server.reset()
    for i in range(1, 601):
        mock_server.state.tickets[i] = {"id": i, "subject": f"PM AT OMNIMART X ({i:06d})", "status": 2, "updated_at": "2026-01-01T00:00:00Z"}
    client = FieldServeClient(mock_server.url, KEY, requests_per_minute=100000)
    with caplog.at_level(logging.WARNING):
        found = client.list_all()
    # The API cannot page past 500 rows with one timestamp; we must terminate
    # and say so rather than loop forever.
    assert 500 <= len(found) <= 600
    assert any("share updated_at" in r.message for r in caplog.records)


def test_catch_up_pass_reads_a_ticket_changed_during_the_scan(mock_server):
    mock_server.reset(count=60)
    client = FieldServeClient(mock_server.url, KEY, requests_per_minute=100000)
    original = client.list_page
    state = {"done": False}

    def racing(page, since, per_page=50):
        batch = original(page, since, per_page)
        if not state["done"]:
            state["done"] = True
            mock_server.put(110, status=5, manager="Late Edit")  # changes mid-scan
        return batch

    client.list_page = racing
    found = client.list_all()
    assert found[110].manager == "Late Edit"


def test_429_is_honoured_and_retried(mock_server):
    """The server allows 2 requests per window; the third gets 429 + Retry-After.

    The client must wait (Retry-After + 1 seconds), then succeed, not fail.
    """
    mock_server.reset(count=5)
    mock_server.state.rate_limit = 2
    waits = []
    client = FieldServeClient(mock_server.url, KEY, requests_per_minute=100000, sleep=waits.append)
    client._limiter._sleep = waits.append  # noqa: SLF001

    client.agents()
    client.agents()

    def lift_the_limit(seconds):
        waits.append(seconds)
        mock_server.state.rate_limit = 100000  # the window "resets" while we wait

    client._limiter._sleep = lift_the_limit  # noqa: SLF001
    assert client.agents()  # 429 -> sleep -> retry -> 200
    assert mock_server.state.rejected_429 == 1
    assert waits == [2.0]  # Retry-After: 1, plus our 1s margin


def test_rejections_are_not_retried(mock_server):
    mock_server.reset(count=5)
    client = FieldServeClient(mock_server.url, KEY, requests_per_minute=100000)
    before = client.request_count
    with pytest.raises(ApiError) as err:
        client.update_ticket(101, {"subject": "not writable"})
    assert err.value.status == 400 and err.value.is_rejection
    assert client.request_count - before == 1


def test_unauthorised_is_an_error(mock_server):
    client = FieldServeClient(mock_server.url, "wrong", requests_per_minute=100000)
    with pytest.raises(ApiError) as err:
        client.agents()
    assert err.value.status == 401


@pytest.mark.parametrize(
    "raw",
    [
        {"id": 1, "subject": "x", "requester": {"email": "a@b.c"}},
        {"id": 1, "subject": "x", "requester_email": "a@b.c"},
        {"id": 1, "subject": "x", "email": "a@b.c"},
    ],
)
def test_requester_email_is_found_in_the_common_shapes(raw):
    assert parse_ticket(raw).requester_email == "a@b.c"


def test_custom_fields_envelope_and_nulls_are_understood():
    t = parse_ticket({"id": 3, "status": "4", "engineer_id": None, "custom_fields": {"manager": " Ann ", "invoice": None}})
    assert (t.id, t.status, t.engineer_id, t.manager) == (3, 4, None, "Ann")
    assert "invoice" in t.null_fields


def test_updated_since_has_no_microseconds():
    from datetime import datetime, timezone

    from fieldserve_board.client import format_updated_since

    assert format_updated_since(datetime(2026, 1, 31, 1, 2, 3, 999999, tzinfo=timezone.utc)) == "2026-01-31T01:02:03Z"
    assert iso(datetime(2026, 1, 31, tzinfo=timezone.utc)) == "2026-01-31T00:00:00Z"
