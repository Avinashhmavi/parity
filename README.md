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

> **Verification status.** The read path has run against the live API (1,007 tickets, 23 requests, from an AWS VPS). The write path has been verified against the local mock only until `deploy/live-check.sh` is run. Details of what the live API turned out to look like are under [Assumptions](#assumptions).
>
> *Original note, from before the live API was reachable:* Everything below was verified against a local mock of the API built from the brief (`fieldserve_board/devtools/mock_api.py`). The live host (`http://13.233.55.184:8377`) was **not reachable** from the environment this was built in, so the real API's JSON envelope was never observed. The client reads the common shapes (a bare list, or `tickets` / `data` / `results` wrappers; requester under `requester.email`, `requester_email` or `email`; fields top-level or under `custom_fields`). Run `python3 sync.py --probe` once against the real API to confirm; see [Assumptions](#assumptions).

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

## Using the board (for people who have never seen it)

The web page is written for someone opening it for the first time, in plain words and in a light theme only:

- **Home** says where things stand in one sentence, then who has the most work waiting and how many jobs sit at each of the six steps. Every number is a button.
- **All Jobs** lists each job with a sentence such as "Nefo Zagi needs to get the customer's Purchase Order", a six-dot progress bar and, when something is wrong, the problem in plain words. Search and four simple filters narrow it down.
- **Needs a Look** shows only jobs with a problem (a Closed job still missing its Invoice, a "will upload" typed where a link belongs) and says how to fix each.
- **People** lists everyone grouped by what they do, with how many jobs wait on each.
- **History** shows what was sent to FieldServe, changes that clashed (and which version was kept), and which emails were ignored as spam or automatic alerts.
- A first-visit guide explains the six steps and the words used; the **Help** button reopens it. Opening a job shows its checklist and one form with one **Save changes** button, which saves to the sheet and sends it to FieldServe straight away. A **Not needed** button fills in the exact waiver text `NA`.

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

- **Rate limit (60/min).** A sliding-window limiter spaces our own requests at 50/min (`API_REQUESTS_PER_MINUTE`). The budget belongs to the API *key*, not to a process, so the window is shared through a small file in the data directory: the web app's scheduled sync, `sync.py` and the check scripts all draw on one budget, and a `429` seen by one pauses the others. (Found on the live API: separate per-process windows added up to well over 60/min.) If a `429` still arrives, we sleep `Retry-After + 1` s, clear our window and retry, up to 6 times, never in a tight loop ("hammering resets the window"). Connection errors and 5xx use exponential backoff. 4xx validation errors are never retried.
- **Pagination cap (10 pages x 50 = 500).** A window is sorted by `updated_at` ascending. When a window comes back full, `updated_since` moves to the timestamp of its last ticket and the next window is fetched; the overlap (tickets sharing that second) is de-duplicated by id. We never request page 11. `updated_since` is sent as `YYYY-MM-DDTHH:MM:SSZ` (no microseconds).
- **Live data.** Tickets edited mid-scan jump to the end of the ordering and could be skipped. After the scan a **catch-up** pass re-lists everything updated since just before the scan began, using the server's own clock (HTTP `Date` header) so clock skew can't hide a change.
- **Known limit:** more than 500 tickets sharing a single `updated_at` second cannot be paged past with this API. The scan steps over that second, logs a warning and terminates rather than looping.
- **Cost.** A full sync of ~600 tickets is about 15 requests. `python3 sync.py --incremental` lists only tickets updated since the last checkpoint (minus 60 s overlap). Full is the default because it also detects tickets that vanished (confirmed with a `GET`, and refused if dozens go missing at once, which is more likely a listing problem than deletions).
- Each pushed ticket costs 2 requests (re-read + `PUT`), so a large batch of edits is throttled, not failed.
- **Clearing a field.** The live API answers `200` to a `PUT` that blanks a field it does not understand and leaves the old value in place. So a clear is sent on its own, as `null` first and then as `""`, and the response is checked. If nothing works (an engineer cannot be unassigned with `null` on some APIs), the edit is refused, logged on the Activity sheet, and the cell goes back to the server's value, so the sheet never claims something the API did not accept.

## Noise

Tickets that are not work (automated alerts, marketing) are kept off `Tickets` and listed on `Noise` with a reason, so a wrong call is visible and reversible. Principles (`fieldserve_board/noise.py`):

- **Conservative**: a real ticket on the Noise sheet is worse than spam on the board.
- **A store code is proof of work**: if a store can be identified the ticket stays, whatever else it says.
- Noise requires evidence: spam wording from a non-trusted sender; an automated mailbox (`no-reply@`, `alerts@`, `mailer-daemon@`…) with no store; machine-only wording ("Delivery Status Notification", "out of office"); or alert-style wording with no store *and* no job type. Senders on `TRUSTED_EMAIL_DOMAINS` (default `omnimart.example`) are given the benefit of the doubt.
- Re-evaluated every sync: a ticket that gains a store code moves onto the board.

Tuned on the live dataset's report (1,007 tickets; `deploy/report.sh`):

- **Bulk-mail sender domains** (`promomail.example`: "Grow your business with a Premium Listing", "Your listing has N potential customers waiting", "Lease opportunity at prime commercial location"): the sender's domain label contains `promo`, `marketing`, `newsletter`, `bulk`, `deals`, `offers`, `campaign` or `advert`, and is not a trusted domain.
- **Automated alert templates** ("DVR OFFLINE ALERT - DEVICE 48213", "MISSED CALL ALERT FROM 98…", "MONTHLY USAGE QUOTA LIMIT EXCEEDED FOR ACCOUNT 55120"): alert vocabulary **plus a device/account/phone number**. This rule runs even when a store code is present, because these senders reuse store mailboxes.
- **Kept on purpose:** a person chasing a bill ("Re: Reminder 5 Outstanding payment from DITI 4 branches"), quotation threads, site surveys, complaints. They are not alerts or marketing; they are work for Finance or the manager, so they stay on the board where someone can act on them. That is a judgement call; say so if you disagree and it is a one-line rule to change.

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
- The web app has **optional HTTP Basic login** (`BOARD_USER`/`BOARD_PASSWORD`, constant-time compare, covers the API, the UI and the websocket; only `/api/live` is open, for Docker health checks). With no password set it logs a warning and should only be used on localhost. Basic auth sends credentials in clear text over plain HTTP, so on a server keep it bound to localhost and reach it through an SSH tunnel, or put TLS in front of it.
- Cut consciously: no per-field audit history beyond `Conflicts`/`Activity`; no webhook-driven (push) syncing; no multi-user presence.

## Assumptions

1. **Observed on the live API:** `/agents` and `/tickets` return a bare JSON list; each ticket carries `requester_name` and `requester_email` at the top level; `reports_to` on an agent is the manager's *name* (not an id); store codes appear bare in subjects (`PM At OMNIMART M9GDCU 2ND MEKANZU DVR`) and are repeated in `requester_name` (`OmniMart Rarsi (M9GDCU)`) and the email (`store.m9gdcu@omnimart.example`). The client still tolerates wrapped lists and `custom_fields`. Auth is HTTP Basic with the key as username.
2. `PUT` accepts `null` to clear `engineer_id`/`manager`; document clears mirror whatever the API returned for empties (`null` vs `""`). A refusal is surfaced as `rejected` and the cell reverts.
3. `updated_since` is inclusive (`>=`) or exclusive; either way the window logic re-reads the boundary second, so ties are safe.
4. "Finance" is a single shared mailbox: the first Finance agent by name.
5. `manager` on a ticket is compared case-insensitively to roster managers; Action Owner shows the roster spelling.
6. If fewer than two coordinators exist, the coordinator rule falls back to the only one.

## Deploying to a VPS

`deploy/deploy.sh` ships the committed repo over ssh and starts the Docker stack; `deploy/verify.sh` then proves it works against the **real** API from the server. Run it from your own machine:

```bash
deploy/deploy.sh ~/keys/test.pem          # DEPLOY_HOST=ubuntu@host to override the target
```

It installs Docker if missing, uploads `git archive HEAD` (so no local secrets or untracked files travel), asks for the FieldServe key and a board password and writes them to `.env` **on the server** over ssh stdin (never on a command line or in the repo), builds, starts, and runs `verify.sh`, which checks the web app is up, the login is enforced, prints the API's real response shapes (`sync.py --probe`), runs one full sync, and prints the per-person summary.

Afterwards, on the server (`ssh ... 'cd fieldserve-board && bash deploy/<script>'`):

- `deploy/report.sh`: a compact data-quality report (counts and samples) for tuning the noise and extraction rules on the real data.
- `deploy/live-check.sh`: verifies the **write** path against the real API by temporarily changing one ticket (document, status, engineer, both-sides-at-once, same-field conflict) and restoring it. Only run it on a dataset you may modify.

**HTTPS address.** From an `ec2-A-B-C-D…` hostname or a bare IP, `deploy.sh` derives `A-B-C-D.sslip.io` (sslip.io resolves that name to the IP, so there is no DNS to set up), writes `DOMAIN` and `COMPOSE_PROFILES=tls` to the server's `.env`, and starts a Caddy container that obtains and renews a Let's Encrypt certificate. Then open `https://13-233-251-144.sslip.io`. Requirements and caveats:

- The instance's **Security Group must allow inbound TCP 80 and 443** from `0.0.0.0/0` (EC2, Instances, Security, Edit inbound rules). Without that the browser shows "refused" or times out.
- A public IP that changes when the instance is stopped and started changes the name; attach an Elastic IP to keep it stable.
- sslip.io is a shared domain, so Let's Encrypt rate limits can occasionally apply; Caddy falls back to another certificate authority automatically. For anything lasting, use your own domain: `DEPLOY_DOMAIN=board.example.com deploy/deploy.sh key.pem` (point an A record at the server first). `DEPLOY_DOMAIN=none` keeps it tunnel-only.
- **Login.** While testing, `deploy.sh` leaves the login **off** (the page shows a "Test mode" bar, and anyone with the link can view and change the board). Turn it on with `BOARD_LOGIN=on deploy/deploy.sh key.pem`; it then asks for a password (user `board`) and throttles failed attempts (10 wrong passwords from one address locks it out for 5 minutes). From your own machine, `deploy/check-live.sh` checks the whole public site end to end.

Without the `tls` profile the container publishes on the server's `127.0.0.1:8000` only; reach it with `ssh -i key -L 8000:127.0.0.1:8000 ubuntu@host` and open `http://localhost:8000`.

## Tests

```bash
pip install -r requirements-dev.txt
ruff check . && pytest --cov=fieldserve_board     # 189 tests: workflow, extraction, noise, merge, client, sync e2e, web, gsheets
cd client && npm test && npm run build            # 6 UI helper tests + production build
```

The end-to-end tests run the real engine over real HTTP against the mock API and a real `.xlsx` on disk. They cover: first sync; idempotence; server change → sheet; sheet edit → API; both sides at once (different fields and same field); stale cells never overwriting; rejected edits; one bad field not blocking a good one; edits landing mid-sync; failed push retried; lost state file; windowing past 500 tickets; `429`/`Retry-After`; noise; `sheet.py export`/`apply`.

## What I'd do next

1. Run `sync.py --probe` against the live API and fix any envelope differences; tune the noise heuristics on the real data.
2. Run the Google backend against a real spreadsheet.
3. Live formulas for Stage/Owner in a second sheet view for people editing in Excel, kept consistent with the Python rules by a test that recalculates in LibreOffice.
4. Sync on change instead of on a timer: the API offers no webhook or ETag, so ask its owners for one rather than polling harder against a 60/min budget.
5. Per-user accounts and attribution of edits (today there is one shared login), and TLS termination in the stack.
