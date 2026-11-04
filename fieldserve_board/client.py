"""HTTP client for the FieldServe helpdesk API.

Handles the three things the API makes awkward:

* **Rate limit** (60 requests/minute/key). A sliding-window limiter spaces our
  own requests so we stay under it; if the server still answers 429 we sleep
  for ``Retry-After`` and retry. We never "hammer", because that resets the
  server's window.
* **Pagination cap** (``page`` > 10 is a 400, ``per_page`` <= 50, so one
  listing shows at most 500 tickets). :meth:`list_all` slides an
  ``updated_since`` window forward until every ticket has been seen.
* **Live data**. Tickets change while we scan, so a catch-up pass re-reads
  everything touched during the scan.
"""

from __future__ import annotations

import collections
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Deque, Dict, Iterable, List, Optional

import requests

from .models import STATUS_CODES, Agent, Ticket

log = logging.getLogger(__name__)

PAGE_SIZE = 50
MAX_PAGES = 10
WINDOW = PAGE_SIZE * MAX_PAGES
EPOCH = "1970-01-01T00:00:00Z"
_UPDATED_SINCE_FMT = "%Y-%m-%dT%H:%M:%SZ"  # the API rejects microseconds


class ApiError(RuntimeError):
    def __init__(self, status: int, message: str, *, method: str = "", url: str = ""):
        super().__init__(f"{method} {url} -> HTTP {status}: {message}".strip())
        self.status = status
        self.message = message

    @property
    def is_rejection(self) -> bool:
        """The server understood and refused (validation); retrying is futile."""
        return self.status in (400, 404, 409, 422)


class RateLimiter:
    """Sliding window: at most ``limit`` calls in any ``period`` seconds."""

    def __init__(
        self,
        limit: int = 55,
        period: float = 60.0,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if limit < 1:
            raise ValueError("limit must be >= 1")
        self.limit = limit
        self.period = period
        self._clock = clock
        self._sleep = sleep
        self._stamps: Deque[float] = collections.deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = self._clock()
                while self._stamps and now - self._stamps[0] >= self.period:
                    self._stamps.popleft()
                if len(self._stamps) < self.limit:
                    self._stamps.append(now)
                    return
                wait = self.period - (now - self._stamps[0])
            self._sleep(max(wait, 0.01))

    def penalise(self, seconds: float) -> None:
        """After a 429: forget our history and hold off for ``seconds``."""
        self._sleep(max(seconds, 0))
        with self._lock:
            self._stamps.clear()


def format_updated_since(value: datetime) -> str:
    value = value.astimezone(timezone.utc).replace(microsecond=0)
    return value.strftime(_UPDATED_SINCE_FMT)


def parse_timestamp(text: str) -> Optional[datetime]:
    """Parse the API's ISO-8601 timestamps (with or without Z / fractions)."""
    if not text:
        return None
    raw = text.strip()
    if raw.endswith(("Z", "z")):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# --------------------------------------------------------------------------
# JSON -> model. The brief fixes the writable field names; the list envelope
# and the requester shape are not spelled out, so both are read defensively.
# --------------------------------------------------------------------------


def _unwrap_list(payload: Any, keys: Iterable[str]) -> List[dict]:
    if isinstance(payload, list):
        return [p for p in payload if isinstance(p, dict)]
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return [p for p in value if isinstance(p, dict)]
    raise ApiError(0, f"unexpected list payload shape: {type(payload).__name__}")


def _unwrap_object(payload: Any, keys: Iterable[str]) -> dict:
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, dict) and "id" in value:
                return value
        return payload
    raise ApiError(0, f"unexpected object payload shape: {type(payload).__name__}")


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _int_or_none(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_ticket(raw: dict) -> Ticket:
    custom = raw.get("custom_fields") if isinstance(raw.get("custom_fields"), dict) else {}

    def pick(name: str) -> Any:
        if name in raw:
            return raw[name]
        return custom.get(name)

    requester = raw.get("requester") if isinstance(raw.get("requester"), dict) else {}
    email = requester.get("email") or raw.get("requester_email") or raw.get("email") or raw.get("from_email") or ""
    name = requester.get("name") or raw.get("requester_name") or ""
    doc_fields = ("manager", "purchase_order", "delivery_note", "work_report", "invoice")
    return Ticket(
        id=int(raw["id"]),
        subject=_text(raw.get("subject")),
        status=_int_or_none(raw.get("status")),
        engineer_id=_int_or_none(pick("engineer_id")),
        manager=_text(pick("manager")).strip(),
        purchase_order=_text(pick("purchase_order")).strip(),
        delivery_note=_text(pick("delivery_note")).strip(),
        work_report=_text(pick("work_report")).strip(),
        invoice=_text(pick("invoice")).strip(),
        updated_at=_text(raw.get("updated_at")),
        created_at=_text(raw.get("created_at")),
        requester_email=_text(email).strip(),
        requester_name=_text(name).strip(),
        null_fields=frozenset(f for f in doc_fields if pick(f) is None),
    )


def parse_agent(raw: dict) -> Agent:
    return Agent(
        id=int(raw["id"]),
        name=_text(raw.get("name")).strip(),
        role=_text(raw.get("role")).strip(),
        team=_text(raw.get("team")).strip(),
        reports_to=_text(raw.get("reports_to")).strip(),
    )


class FieldServeClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        requests_per_minute: int = 55,
        timeout: float = 20.0,
        max_retries: int = 6,
        session: Optional[requests.Session] = None,
        limiter: Optional[RateLimiter] = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = session or requests.Session()
        self._session.auth = (api_key, "x")
        self._session.headers.update({"Accept": "application/json"})
        self._limiter = limiter or RateLimiter(requests_per_minute, sleep=sleep)
        self._sleep = sleep
        self.request_count = 0
        self.server_time: Optional[datetime] = None  # from the HTTP Date header
        self._scan_start_server_time: Optional[datetime] = None

    # -- transport -------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.base_url}{path}"
        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            self._limiter.acquire()
            self.request_count += 1
            try:
                response = self._session.request(method, url, timeout=self.timeout, **kwargs)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = exc
                self._sleep(min(2**attempt, 15))
                continue

            self._note_server_time(response)
            if response.status_code == 429:
                delay = _retry_after(response) + 1
                log.warning("429 from %s %s, waiting %.0fs", method, path, delay)
                self._limiter.penalise(delay)
                continue
            if response.status_code >= 500:
                last_error = ApiError(response.status_code, response.text[:200], method=method, url=url)
                self._sleep(min(2**attempt, 15))
                continue
            if response.status_code >= 400:
                raise ApiError(response.status_code, _error_message(response), method=method, url=url)
            if not response.content:
                return None
            try:
                return response.json()
            except ValueError as exc:
                raise ApiError(response.status_code, "response was not JSON", method=method, url=url) from exc
        raise ApiError(0, f"gave up after {self.max_retries + 1} attempts: {last_error}", method=method, url=url)

    def _note_server_time(self, response: requests.Response) -> None:
        header = response.headers.get("Date")
        if not header:
            return
        try:
            self.server_time = parsedate_to_datetime(header).astimezone(timezone.utc)
        except (TypeError, ValueError):
            return
        if self._scan_start_server_time is None:
            self._scan_start_server_time = self.server_time

    # -- endpoints -------------------------------------------------------

    def agents(self) -> List[Agent]:
        payload = self._request("GET", "/api/v2/agents")
        return [parse_agent(a) for a in _unwrap_list(payload, ("agents", "data", "results", "items"))]

    def get_ticket(self, ticket_id: int) -> Ticket:
        payload = self._request("GET", f"/api/v2/tickets/{int(ticket_id)}")
        return parse_ticket(_unwrap_object(payload, ("ticket", "data")))

    def update_ticket(self, ticket_id: int, changes: Dict[str, Any]) -> Optional[Ticket]:
        """Sparse PUT. Returns the updated ticket when the response carries it."""
        payload = self._request("PUT", f"/api/v2/tickets/{int(ticket_id)}", json=changes)
        if payload is None:
            return None
        try:
            return parse_ticket(_unwrap_object(payload, ("ticket", "data")))
        except (KeyError, ValueError, ApiError):
            return None

    def list_page(self, page: int, updated_since: str, per_page: int = PAGE_SIZE) -> List[Ticket]:
        params = {"page": page, "per_page": per_page, "updated_since": updated_since}
        payload = self._request("GET", "/api/v2/tickets", params=params)
        return [parse_ticket(t) for t in _unwrap_list(payload, ("tickets", "data", "results", "items"))]

    # -- enumeration -----------------------------------------------------

    def list_all(self, updated_since: str = EPOCH, *, catch_up: bool = True) -> Dict[int, Ticket]:
        """Every ticket updated at or after ``updated_since``, by id.

        A listing is capped at 500 tickets (10 pages x 50), sorted by
        ``updated_at`` ascending. When a window comes back full we move
        ``updated_since`` up to the timestamp of its last ticket and fetch the
        next window; the overlap (tickets that share that second) is
        de-duplicated by id. Ties are why the window moves to the last
        timestamp rather than past it.
        """
        local_start = datetime.now(timezone.utc)
        self._scan_start_server_time = None
        found = self._scan(updated_since)
        if catch_up:
            # The data is live: tickets edited during the scan jumped to the end
            # of the ascending order and may have been skipped or double-read.
            # Re-read everything touched since just before the scan started,
            # using the server's own clock (HTTP Date) so skew cannot hide one.
            anchor = self._scan_start_server_time or local_start
            since = format_updated_since(anchor - timedelta(seconds=90))
            for ticket_id, ticket in self._scan(max(since, updated_since)).items():
                found[ticket_id] = ticket
        return found

    def _scan(self, updated_since: str) -> Dict[int, Ticket]:
        found: Dict[int, Ticket] = {}
        since = updated_since
        while True:
            window: List[Ticket] = []
            for page in range(1, MAX_PAGES + 1):
                batch = self.list_page(page, since)
                window.extend(batch)
                if len(batch) < PAGE_SIZE:
                    break
            for ticket in window:
                # later = newer within one scan, so let it overwrite.
                found[ticket.id] = ticket
            if len(window) < WINDOW:
                return found

            last = parse_timestamp(window[-1].updated_at)
            first = parse_timestamp(window[0].updated_at)
            if last is None:
                log.warning("window ended on a ticket without a usable updated_at; stopping the scan")
                return found
            next_since = format_updated_since(last)
            if next_since <= since:
                # All 500 share one second, so the window cannot move without
                # skipping. Step past it and say so; >500 tickets in a single
                # second would be lost, which we cannot do better on without
                # a different API.
                stepped = format_updated_since(last + timedelta(seconds=1))
                log.warning("500 tickets share updated_at %s (first=%s); stepping to %s", next_since, first, stepped)
                next_since = stepped
            since = next_since


def _retry_after(response: requests.Response) -> float:
    header = response.headers.get("Retry-After", "")
    try:
        return max(float(header), 0.0)
    except ValueError:
        return 5.0 if not header else _http_date_delay(header)


def _http_date_delay(header: str) -> float:
    try:
        when = parsedate_to_datetime(header)
    except (TypeError, ValueError):
        return 5.0
    return max((when - datetime.now(timezone.utc)).total_seconds(), 0.0)


def _error_message(response: requests.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:300]
    if isinstance(body, dict):
        for key in ("message", "error", "detail", "errors"):
            if key in body:
                return str(body[key])[:300]
    return str(body)[:300]


def status_code_for(label: str) -> Optional[int]:
    return STATUS_CODES.get(label)
