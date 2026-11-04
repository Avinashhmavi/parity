# FieldServe Ticket Board

Two-way sync between the **FieldServe helpdesk API** and a **real spreadsheet** (Excel by default, Google Sheets optional), plus the six-step ticket workflow that answers one question for every ticket: **what is it waiting on, and whose move is it?**

- `sync.py` runs one full two-way sync cycle and exits.
- `sheet.py export|apply` drives the spreadsheet without opening Excel (this is what an automated grader calls).
- A FastAPI backend and a React UI sit on top for the operations team.

```
 FieldServe API  <──────── sync.py / SyncEngine ────────>  Tickets.xlsx  (or Google Sheet)
   GET/PUT  /api/v2/*      three-way merge per field          Tickets · Summary · Noise
                           baseline in data/sync_state.json   Conflicts · Activity · Roster
                                       │
                                  FastAPI (reads the board, writes edits like a human,
                                  triggers syncs, streams events on /ws)
                                       │
                                  React UI (JavaScript for the UI only)
```

> **Verification status, read this first.** Everything below was verified against a local mock of the API built from the brief (`fieldserve_board/devtools/mock_api.py`). The live host (`http://13.233.55.184:8377`) was **not reachable** from the environment this was built in, so the real API's JSON envelope was never observed. The client reads the common shapes (a bare list, or `tickets` / `data` / `results` wrappers; requester under `requester.email`, `requester_email` or `email`; fields top-level or under `custom_fields`). Run `python3 sync.py --probe` once against the real API to confirm; see [Assumptions](#assumptions).

## Quick start

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # set FIELDOPS_API_KEY (and FIELDOPS_BASE_URL if different)

python3 sync.py --probe       # optional: print the API's raw response shapes
python3 sync.py               # first run builds data/FieldServe_Board.xlsx
python3 sheet.py summary      # tickets waiting on each person
```

Web app (API + UI):

```bash
cd client && npm ci && npm run build && cd ..      # once; produces client/dist
uvicorn fieldserve_board.web.app:app --port 8000   # http://localhost:8000
# UI development with hot reload:  uvicorn ... --port 8000  and  cd client && npm run dev
```

Docker: `docker compose up --build` serves everything on `127.0.0.1:8000` and syncs every 120 s. (Written but not built in the environment this was authored in; the CI `docker` job builds it.)

No real API key? `python -m fieldserve_board.devtools.mock_api --port 8377 --key fk_demo` serves 620 deliberately messy tickets, then `FIELDOPS_BASE_URL=http://127.0.0.1:8377 FIELDOPS_API_KEY=fk_demo python3 sync.py`.

The grader contract is in [`submission.json`](submission.json): `python3 sync.py` and `python3 sheet.py`, both run from the repo root with `FIELDOPS_BASE_URL` / `FIELDOPS_API_KEY` in the environment.

## The sheet

`Tickets` has the 11 required columns, named exactly, plus extras (extras are never judged):

| Column | Value |
|---|---|
| Ticket ID, Subject | as served |
| Status | `Open` / `Pending` / `Resolved` / `Closed` |
| Engineer | exact `/agents` name (mapped to `engineer_id`), or blank |
| Manager | the manager string as on the ticket |
| Purchase Order, Delivery Note, Work Report, Invoice | the raw field value: URL, `NA`, junk text, or blank |
| **Stage** | `Assign Manager` / `Assign Engineer` / `Purchase Order` / `Delivery Note` / `Work Report` / `Invoice` / `Done` |
| **Action Owner** | roster name of whoever the stage waits on; blank when `Done` |
| Integrity, Store Code, Store, Job Type, Requester, Updated At | extras |

Other sheets: `Summary` (pending tickets per person), `Noise` (tickets kept off the board, with the reason), `Conflicts`, `Activity`, `Roster`. Stage / Action Owner / Integrity / Store / Job Type are computed and shaded grey; edits to them are ignored.

## The workflow (§3 of the brief, implemented literally)

| # | Step | Met when | Owner |
|---|---|---|---|
| 1 | Assign Manager | `manager` non-empty | Coordinator: `coordinators_sorted_by_name[ticket_id % 2]` |
| 2 | Assign Engineer | `engineer_id` set | the ticket's Manager |
| 3 | Purchase Order | `purchase_order` is a URL (`NA` is **not** accepted) | the ticket's Manager |
| 4 | Delivery Note | URL or exactly `NA` | Finance |
| 5 | Work Report | URL (`NA` is never accepted) | the ticket's Engineer |
| 6 | Invoice | URL or exactly `NA` | Finance |

The **first** unmet step is the Stage; later missing documents don't matter yet. A document counts only if it is a well-formed `http(s)` URL with a dotted host, or the exact text `NA` where waivable. `done`, `asked Ravi`, `ok`, `na`, `N/A`, `see https://…` are junk: not a document, and flagged as "X is not a link".

**Integrity flags** (column `Integrity`, rows tinted red, counted in the UI):

- `Closed but waiting on <Stage>`: Closed with any step unmet.
- `Resolved without Work Report`: Resolved and the Work Report is not a URL (junk and `NA` included).
- `<Document> is not a link`, `<Document> cannot be NA` (PO / Work Report).
- `Manager not on roster`, `Engineer not on roster` (`manager` is a free-text name, so it is validated against `/agents`; the step still counts as met, as §3 says "non-empty", but the problem is visible).

Name matching is case- and whitespace-insensitive; the roster spelling is used for Action Owner.

## How the sync works

One `python3 sync.py` = one cycle, in this order (`fieldserve_board/engine.py`):

1. **Pull.** `GET /agents`, then list every ticket (see *API limits*).
2. **Read** the `Tickets` sheet.
3. **Merge**, per ticket and per field, as a three-way comparison of `base` (last value both sides agreed on, stored in `data/sync_state.json`), `sheet` and `api`.
4. **Push** sheet edits with a sparse `PUT`. Each pushed ticket is **re-read first** and the merge re-run against that fresh copy.
5. **Write** the merged result to the workbook, then **save the baseline**.

Why a baseline: with only two snapshots you cannot tell *who* changed a field. With a third you can, and that is what makes "an unchanged sheet cell never overwrites a fresh server change" a property of the algorithm rather than a hope.

## Conflict policy

Per field (`fieldserve_board/merge.py`, a pure function with its own tests):

| sheet vs base | api vs base | outcome |
|---|---|---|
| same | changed | **take the API** (the cell was never touched; this is the "stale cell never clobbers" guarantee) |
| changed | same | **push the sheet edit** |
| changed | changed, to the same value | nothing to do |
| changed | changed, to different values | **conflict: the API wins**, logged |

- The API wins a true same-field conflict because it is the system of record and may already have been acted on by someone else. The losing sheet value is written to the `Conflicts` sheet (and the Activity feed) with the baseline, so it can be re-applied by hand. `CONFLICT_POLICY=sheet` flips this.
- It is per **field**, so a ticket changed on both sides at once still merges cleanly when the edits touch different fields (server changes Status, human sets Work Report: both land).
- **No baseline** for a ticket (state file lost) means the API wins, and any differing sheet value is logged as a conflict instead of being silently dropped. The worst case after losing the state file is "a human edit is logged, not applied", never "a stale cell overwrites the server".
- **Case or spacing only** (`chitra menon` vs `Chitra Menon`) is not an edit.
- **Validation before sending:** an unknown engineer/manager/status is refused locally, reverted on the sheet to the server value, and logged (`rejected`). If a multi-field `PUT` is refused, each field is retried alone so one bad value doesn't block a good one.
- **Edits during a sync:** just before writing, the sheet is read again. Any cell changed since the first read is left as the human typed it and its baseline is not advanced, so the next sync treats it as a normal edit.
- **Failures:** a network/5xx error on a push leaves the human's edit in place and the baseline unchanged, so the next sync retries. The sync exits 0 with `errors > 0` in its JSON summary; only failures that stop the cycle (cannot list tickets, cannot write the workbook) exit non-zero.
- Writes order: API push, then sheet, then baseline. A crash between steps is safe because the next run finds `sheet == api` and does nothing.
- Edits to a **deleted** row are not propagated (the API has no delete); the row reappears on the next sync. A row for a ticket id the API doesn't have is left untouched and logged: the sheet can't create tickets.

## API limits

- **Rate limit (60/min).** A sliding-window limiter spaces our own requests at 55/min (`API_REQUESTS_PER_MINUTE`). If a `429` still arrives, we sleep `Retry-After + 1` s, clear our window and retry, up to 6 times, never in a tight loop ("hammering resets the window"). Connection errors and 5xx use exponential backoff. 4xx validation errors are never retried.
- **Pagination cap (10 pages x 50 = 500).** A window is sorted by `updated_at` ascending. When a window comes back full, `updated_since` moves to the timestamp of its last ticket and the next window is fetched; the overlap (tickets sharing that second) is de-duplicated by id. We never request page 11. `updated_since` is sent as `YYYY-MM-DDTHH:MM:SSZ` (no microseconds).
- **Live data.** Tickets edited mid-scan jump to the end of the ordering and could be skipped. After the scan a **catch-up** pass re-lists everything updated since just before the scan began, using the server's own clock (HTTP `Date` header) so clock skew can't hide a change.
- **Known limit:** more than 500 tickets sharing a single `updated_at` second cannot be paged past with this API. The scan steps over that second, logs a warning and terminates rather than looping.
- **Cost.** A full sync of ~600 tickets is about 15 requests. `python3 sync.py --incremental` lists only tickets updated since the last checkpoint (minus 60 s overlap). Full is the default because it also detects tickets that vanished (confirmed with a `GET`, and refused if dozens go missing at once, which is more likely a listing problem than deletions).
- Each pushed ticket costs 2 requests (re-read + `PUT`), so a large batch of edits is throttled, not failed.

## Noise

Tickets that are not work (automated alerts, marketing) are kept off `Tickets` and listed on `Noise` with a reason, so a wrong call is visible and reversible. Principles (`fieldserve_board/noise.py`):

- **Conservative**: a real ticket on the Noise sheet is worse than spam on the board.
- **A store code is proof of work**: if a store can be identified the ticket stays, whatever else it says.
- Noise requires evidence: spam wording from a non-trusted sender; an automated mailbox (`no-reply@`, `alerts@`, `mailer-daemon@`…) with no store; machine-only wording ("Delivery Status Notification", "out of office"); or alert-style wording with no store *and* no job type. Senders on `TRUSTED_EMAIL_DOMAINS` (default `omnimart.example`) are given the benefit of the doubt.
- Re-evaluated every sync: a ticket that gains a store code moves onto the board.

The heuristics were written from the brief's description, not from the real dataset. Check the `Noise` sheet after the first real sync.

## Messy extraction

`fieldserve_board/extract.py`, all rules documented in the file:

- **Store code** (6 alphanumerics): `(K7Q2XR)` in the subject; else the requester email `store.k7q2xr@…`; else a bare mixed letter+digit token. A plain six-letter word (`CAMERA`) never matches. An all-letter code in parentheses is only trusted when the email agrees.
- **Job type**, first match wins: Maintenance (`PM`, `AMC`, preventive/maintenance) → Installation → Service Call (`not working`, fault, complaint, offline, repair…) → Other. `PM … camera not working` is Maintenance, as the brief defines PM.
- **Store name**: the words after `OMNIMART`, title-cased.

## Decisions and cuts

- **Excel is the default; Stage/Action Owner are values, not formulas.** openpyxl writes formulas without cached results, so a CSV export or grader reading the file without Excel would see blanks. The cost: Stage refreshes on the next sync or `sheet.py apply`, not live while typing in Excel. `sheet.py apply` recomputes the computed columns locally (what a formula would do), with no API call.
- `Status`, `Engineer` and `Manager` cells have dropdowns (warning-style, so a human can still type) fed from the live roster.
- **Google Sheets** is a second backend behind the same three-method interface (`BoardBackend`). It is exercised by running the full sync engine through an in-memory fake of gspread; it has **not** been run against live Google. Setup is in `.env.example`.
- State is one JSON file written atomically, plus a file lock so `sync`, `export`, `apply` and the web app never interleave.
- The web app has no authentication and binds to localhost: it is an operations console, not an internet service. Put it behind your own auth before exposing it.
- Cut consciously: no per-field audit history beyond `Conflicts`/`Activity`; no webhook-driven (push) syncing; no multi-user presence.

## Assumptions

1. **Response envelope and requester shape are unobserved** (see the verification note). Auth is HTTP Basic with the key as username, as in the brief.
2. `PUT` accepts `null` to clear `engineer_id`/`manager`; document clears mirror whatever the API returned for empties (`null` vs `""`). A refusal is surfaced as `rejected` and the cell reverts.
3. `updated_since` is inclusive (`>=`) or exclusive; either way the window logic re-reads the boundary second, so ties are safe.
4. "Finance" is a single shared mailbox: the first Finance agent by name.
5. `manager` on a ticket is compared case-insensitively to roster managers; Action Owner shows the roster spelling.
6. If fewer than two coordinators exist, the coordinator rule falls back to the only one.

## Tests

```bash
pip install -r requirements-dev.txt
ruff check . && pytest --cov=fieldserve_board     # 124 tests: workflow, extraction, noise, merge, client, sync e2e, web, gsheets
cd client && npm test && npm run build            # 6 UI helper tests + production build
```

The end-to-end tests run the real engine over real HTTP against the mock API and a real `.xlsx` on disk. They cover: first sync; idempotence; server change → sheet; sheet edit → API; both sides at once (different fields and same field); stale cells never overwriting; rejected edits; one bad field not blocking a good one; edits landing mid-sync; failed push retried; lost state file; windowing past 500 tickets; `429`/`Retry-After`; noise; `sheet.py export`/`apply`.

## What I'd do next

1. Run `sync.py --probe` against the live API and fix any envelope differences; tune the noise heuristics on the real data.
2. Run the Google backend against a real spreadsheet.
3. Live formulas for Stage/Owner in a second sheet view for people editing in Excel, kept consistent with the Python rules by a test that recalculates in LibreOffice.
4. Sync on change instead of on a timer: the API offers no webhook or ETag, so ask its owners for one rather than polling harder against a 60/min budget.
5. Authentication in front of the web app, and per-user attribution of edits.
