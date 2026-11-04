"""A local FieldServe API, built from section 5 of the take-home brief.

It exists so the sync can be developed and tested without the live host, and
so the UI can be demoed with realistic messy data. It is a test double, not the
real service: where the brief is silent (response envelope, requester field)
it makes one choice, and the client parses the common alternatives too.

Enforced like the real thing:

* HTTP Basic auth (key as username)
* ``per_page`` max 50; ``page`` > 10 -> 400
* ``updated_since`` must look like ``2026-01-31T00:00:00Z`` -> else 400
* listings sorted by ``updated_at`` ascending
* ``PUT`` accepts only the writable fields (else 400); unknown engineer or
  manager -> 422
* rate limit with 429 + ``Retry-After`` (default 60/min, configurable)

Run it:  ``python -m fieldserve_board.devtools.mock_api --port 8377``
"""

from __future__ import annotations

import argparse
import random
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

WRITABLE = {"status", "engineer_id", "manager", "purchase_order", "delivery_note", "work_report", "invoice"}
UPDATED_SINCE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

AGENTS = [
    {"id": 1, "name": "Anita Rao", "role": "Coordinator", "team": "Front Desk", "reports_to": None},
    {"id": 2, "name": "Bilal Khan", "role": "Coordinator", "team": "Front Desk", "reports_to": None},
    {"id": 3, "name": "Chitra Menon", "role": "Manager", "team": "North", "reports_to": None},
    {"id": 4, "name": "Dev Malhotra", "role": "Manager", "team": "South", "reports_to": None},
    {"id": 5, "name": "Esha Pillai", "role": "Engineer", "team": "North", "reports_to": 3},
    {"id": 6, "name": "Farhan Ali", "role": "Engineer", "team": "North", "reports_to": 3},
    {"id": 7, "name": "Gita Nair", "role": "Engineer", "team": "South", "reports_to": 4},
    {"id": 8, "name": "Harish Gowda", "role": "Engineer", "team": "South", "reports_to": 4},
    {"id": 9, "name": "FieldServe Finance", "role": "Finance", "team": "Back Office", "reports_to": None},
]


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class MockState:
    def __init__(self, api_key: str = "fk_test", rate_limit: int = 60):
        self.api_key = api_key
        self.rate_limit = rate_limit
        self.lock = threading.RLock()
        self.tickets: Dict[int, Dict[str, Any]] = {}
        self.hits: List[float] = []
        self.requests_total = 0
        self.rejected_429 = 0
        self.clock_offset = 0.0

    def now(self) -> datetime:
        return datetime.now(timezone.utc) + timedelta(seconds=self.clock_offset)

    def touch(self, ticket: Dict[str, Any]) -> None:
        ticket["updated_at"] = iso(self.now())


def _doc(rng: random.Random, kind: str, ticket_id: int) -> str:
    roll = rng.random()
    if roll < 0.45:
        return f"https://files.fieldserve.example/{kind}/{ticket_id}.pdf"
    if roll < 0.62:
        return ""
    if roll < 0.74:
        return "NA"
    return rng.choice(["done", "asked Ravi", "ok", "will send", "n/a", "pending", "NA ", "see mail"])


def seed_tickets(state: MockState, count: int = 620, seed: int = 7) -> None:
    """Messy, deterministic data: junk documents, noise, ties in updated_at."""
    rng = random.Random(seed)
    base = state.now() - timedelta(days=30)
    managers = [a["name"] for a in AGENTS if a["role"] == "Manager"]
    engineers = [a["id"] for a in AGENTS if a["role"] == "Engineer"]
    stores = ["K7Q2XR", "M3N8PD", "T5W9ZB", "H2J4LC", "R8V6QA", "D1F7GS"]
    towns = ["TARVENO", "VESHOLM", "KARNDALE", "BRIXTON", "OAKMERE", "SALTHAM"]
    for i in range(1, count + 1):
        tid = 100 + i
        store = rng.choice(stores)
        town = rng.choice(towns)
        kind = rng.random()
        email = f"store.{store.lower()}@omnimart.example"
        if kind < 0.05:
            subject = rng.choice(["Limited time offer: 50% OFF CCTV cameras", "Weekly newsletter - unsubscribe", "Free trial of our SEO service"])
            email = rng.choice(["promo@bulkmail.example", "newsletter@deals.example"])
        elif kind < 0.09:
            subject = rng.choice(["[Auto] Disk space threshold exceeded", "Automated alert: heartbeat missed", "Delivery Status Notification (Failure)"])
            email = rng.choice(["no-reply@monitor.example", "alerts@omnimart.example"])
        elif kind < 0.40:
            subject = f"PM AT OMNIMART {town} ({store})"
        elif kind < 0.62:
            subject = f"INSTALLATION AT OMNIMART {town}" + (f" ({store})" if rng.random() < 0.5 else "")
        elif kind < 0.72:
            subject = f"AMC visit OMNIMART {town} ({store})"
        else:
            subject = f"CAMERA NOT WORKING at OMNIMART {town} ({store})"
        stage_roll = rng.random()
        manager = rng.choice(managers) if stage_roll > 0.12 else ""
        engineer = rng.choice(engineers) if manager and stage_roll > 0.22 else None
        updated = base + timedelta(minutes=i * 60 + (0 if i % 40 else -1))  # a few exact ties
        ticket = {
            "id": tid,
            "subject": subject,
            "status": rng.choice([2, 2, 3, 4, 5]),
            "engineer_id": engineer,
            "manager": manager,
            "purchase_order": _doc(rng, "po", tid) if engineer else "",
            "delivery_note": _doc(rng, "dn", tid) if engineer else "",
            "work_report": _doc(rng, "wr", tid) if engineer else "",
            "invoice": _doc(rng, "inv", tid) if engineer else "",
            "created_at": iso(base),
            "updated_at": iso(updated),
            "requester": {"name": "OmniMart Store", "email": email},
        }
        state.tickets[tid] = ticket


def create_app(state: Optional[MockState] = None) -> FastAPI:
    state = state or MockState()
    app = FastAPI(title="Mock FieldServe API", docs_url=None, redoc_url=None)
    app.state.mock = state

    @app.middleware("http")
    async def gate(request: Request, call_next):
        if request.url.path.startswith("/_admin"):
            return await call_next(request)
        with state.lock:
            state.requests_total += 1
            auth = request.headers.get("authorization", "")
            import base64

            user = ""
            if auth.lower().startswith("basic "):
                try:
                    user = base64.b64decode(auth[6:]).decode().split(":", 1)[0]
                except Exception:
                    user = ""
            if user != state.api_key:
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            now = time.monotonic()
            state.hits = [h for h in state.hits if now - h < 60]
            if len(state.hits) >= state.rate_limit:
                state.rejected_429 += 1
                state.hits.append(now)  # hammering resets the window
                return JSONResponse({"error": "rate limit"}, status_code=429, headers={"Retry-After": "1"})
            state.hits.append(now)
        return await call_next(request)

    @app.get("/api/v2/agents")
    def agents():
        return {"agents": AGENTS}

    @app.get("/api/v2/tickets")
    def list_tickets(page: int = 1, per_page: int = 20, updated_since: Optional[str] = None):
        if page < 1 or page > 10:
            return JSONResponse({"error": "page must be between 1 and 10"}, status_code=400)
        if per_page < 1 or per_page > 50:
            return JSONResponse({"error": "per_page must be between 1 and 50"}, status_code=400)
        if updated_since is not None and not UPDATED_SINCE.match(updated_since):
            return JSONResponse({"error": "updated_since must look like 2026-01-31T00:00:00Z"}, status_code=400)
        with state.lock:
            items = sorted(state.tickets.values(), key=lambda t: (t["updated_at"], t["id"]))
            if updated_since:
                items = [t for t in items if t["updated_at"] >= updated_since]
            start = (page - 1) * per_page
            return {"tickets": [dict(t) for t in items[start : start + per_page]]}

    @app.get("/api/v2/tickets/{ticket_id}")
    def get_ticket(ticket_id: int):
        with state.lock:
            ticket = state.tickets.get(ticket_id)
            if ticket is None:
                return JSONResponse({"error": "not found"}, status_code=404)
            return {"ticket": dict(ticket)}

    @app.put("/api/v2/tickets/{ticket_id}")
    async def put_ticket(ticket_id: int, request: Request):
        body = await request.json()
        with state.lock:
            ticket = state.tickets.get(ticket_id)
            if ticket is None:
                return JSONResponse({"error": "not found"}, status_code=404)
            if not isinstance(body, dict) or set(body) - WRITABLE:
                return JSONResponse({"error": f"fields not writable: {sorted(set(body) - WRITABLE)}"}, status_code=400)
            engineer = body.get("engineer_id")
            if engineer is not None and not any(a["id"] == engineer and a["role"] == "Engineer" for a in AGENTS):
                return JSONResponse({"error": "unknown engineer"}, status_code=422)
            manager = body.get("manager")
            if manager not in (None, "") and not any(a["name"] == manager and a["role"] == "Manager" for a in AGENTS):
                return JSONResponse({"error": "unknown manager"}, status_code=422)
            if "status" in body and body["status"] not in (2, 3, 4, 5):
                return JSONResponse({"error": "bad status"}, status_code=422)
            ticket.update(body)
            state.touch(ticket)
            return {"ticket": dict(ticket)}

    # -- test control, not part of the real API -------------------------------

    @app.post("/_admin/mutate/{ticket_id}")
    async def mutate(ticket_id: int, request: Request):
        """Change a ticket server-side, as a manager on their phone would."""
        body = await request.json()
        with state.lock:
            state.tickets[ticket_id].update(body)
            state.touch(state.tickets[ticket_id])
        return {"ok": True}

    @app.post("/_admin/add")
    async def add(request: Request):
        body = await request.json()
        with state.lock:
            body.setdefault("created_at", iso(state.now()))
            state.tickets[body["id"]] = body
            state.touch(body)
        return {"ok": True}

    @app.post("/_admin/limit/{limit}")
    def set_limit(limit: int):
        state.rate_limit = limit
        return {"ok": True}

    @app.get("/_admin/stats")
    def stats():
        return {"requests": state.requests_total, "rejected_429": state.rejected_429, "tickets": len(state.tickets)}

    return app


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="Run a local mock of the FieldServe API (development only).")
    parser.add_argument("--port", type=int, default=8377)
    parser.add_argument("--key", default="fk_demo")
    parser.add_argument("--tickets", type=int, default=620)
    args = parser.parse_args()
    state = MockState(api_key=args.key)
    seed_tickets(state, args.tickets)
    print(f"mock FieldServe API on http://127.0.0.1:{args.port}  (api key: {args.key}, {args.tickets} tickets)")
    uvicorn.run(create_app(state), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
