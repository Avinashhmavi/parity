# Requirements traceability

Every requirement in the take-home brief, how it is met, and the evidence. **Live** means it was observed against the real FieldServe API from the VPS; **Tests** means an automated test (against the local mock API built from the brief); **Judgement** marks a decision the brief leaves open.

Last full test run: 189 backend tests, 10 UI tests, lint clean. The test named in each row is in `tests/`.

## §1 The people

| Requirement | How | Evidence |
|---|---|---|
| Fetch the roster from `GET /api/v2/agents` | `FieldServeClient.agents()`, shown on the `Roster` sheet | **Live**: 19 agents read (2 coordinators, 3 managers, 13 engineers, 1 finance) |
| Coordinator is `coordinators_sorted_by_name[ticket_id % 2]` | `Roster.coordinator_for` | Tests: `test_workflow::test_coordinator_is_chosen_by_id_parity...`, `test_requirements::test_s3_coordinator_is_split_by_ticket_id_parity` |
| Managers pick the engineer and obtain the PO; engineers own the Work Report; Finance owns Delivery Note and Invoice | step owners in `workflow._step_owner` | Tests: `test_workflow::test_assign_engineer_belongs...`, `..._work_report_belongs_to_the_engineer`, differential test (below) |
| `reports_to` | parsed (a manager *name* on the live API) and shown on the `Roster` sheet | **Live** shape observed |

## §2 The paperwork

| Requirement | How | Evidence |
|---|---|---|
| A field is a URL, empty, or the **exact** text `NA`; anything else is junk and does not count | `workflow.classify_document`: `NA` is matched exactly (no trimming, no case folding). `"NA "`, `" NA"`, `"na"`, `"N/A"` are junk | Tests: `test_workflow::test_classify_document` (includes the padded and lower-case forms); **fixed during the audit**: an earlier version trimmed whitespace and would have accepted `"NA "` |
| PO never waivable; Work Report never waivable; DN and Invoice waivable | `STEPS` table | Tests: `test_workflow::test_waiver_rules`, `test_requirements::test_s3_the_briefs_own_examples` |
| You will find junk in the data. Handle it | junk is shown as served, is not a document, is flagged ("X is not a link") | **Live**: 91 junk values handled; the report lists them ("will upload", "ok", "sent on mail", "asked Nefo", "approved on call", "done", "uploading tonight", "with manager", ...) |

## §3 The workflow

| Requirement | How | Evidence |
|---|---|---|
| Six steps in order; first unmet step is the **Stage**; its owner is the **Action Owner**; `Done` when all are met (blank owner) | `workflow.evaluate` | **Differential test**: `test_requirements::test_s3_stage_and_action_owner_match_an_independent_implementation_for_every_row` recomputes every exported row (about 600 messy tickets plus 14 hand-built edge cases) from the raw API JSON with a *second, separate implementation* written from the brief's tables, and requires an exact match |
| Later missing documents do not move the stage | first-unmet semantics | Test: `test_s3_first_unmet_step_wins_when_later_documents_exist` |
| A ticket may be Closed only if all six steps are met: flag otherwise | `Closed but waiting on <Stage>` in `Integrity` | Tests: `test_s3_closed_with_missing_paperwork_is_flagged...`; **Live**: 77 such tickets surfaced |
| Resolved without a Work Report is missing paperwork: flag | `Resolved without Work Report` (junk or `NA` report included) | Tests: `test_s3_resolved_without_a_work_report_is_flagged...`; **Live**: 56 surfaced |
| Per-person count of tickets waiting | `Summary` sheet, `/api/summary`, People page | Tests: `test_s6_summary_counts_equal_what_each_person_is_waiting_on`; **Live**: counts match the sheet |

## §4 The data is messy on purpose

| Requirement | How | Evidence |
|---|---|---|
| Store code (6 alphanumerics) and work type from subject and requester email | `extract.py`: parenthesised or bare code in the subject, in `requester_name`, or in `store.<code>@` email; work type Maintenance (PM, AMC) > Installation > Service Call > Other | Tests: `test_extract_noise`, `test_requirements::test_s4_store_code_and_work_type`; **Live**: store code found for 690 of 1,007 tickets; the rest are people's emails with no code anywhere |
| Decide what is noise, and say why | `noise.py`; kept on a separate `Noise` sheet with a reason per ticket; rules tuned on the live report | **Live**: 31 of 1,007 moved (30 from a bulk-mail domain, 1 marketing wording); `README.md` "Noise" explains each rule and what was deliberately kept (payment reminders, quotations) |
| Document fields may be junk | see §2 | see §2 |
| `manager` is a plain name: validate against the roster | `Manager not on roster` flag; edits to an unknown manager are refused before they are sent | Tests: `test_s4_manager_is_validated_against_the_roster`, `test_sync_e2e::test_invalid_engineer_is_rejected...` |

## §5 The API and its limits

| Requirement | How | Evidence |
|---|---|---|
| `page` > 10 is a 400; one listing shows at most 500; enumerate everything with `updated_since` | sliding `updated_since` windows, overlap de-duplicated by id, never asks for page 11 | Tests: `test_client::test_list_all_walks_past_the_500_ticket_cap...` (1,300 tickets), `..._survives_a_whole_window_sharing_one_timestamp`; **Live**: 1,007 tickets in 23 requests |
| 60 requests/minute, 429 + `Retry-After`, hammering resets the window | sliding-window limiter (50/min default) **shared across processes** through the data directory; `Retry-After + 1` on a 429, never a tight loop | Tests: `test_client` (limiter, 429, shared limiter); **Live**: 429 storm seen on the first live write check led to the shared limiter; later runs are quiet |
| Data is live: tickets change while syncing | catch-up pass after every scan, anchored on the server's own clock | Test: `test_catch_up_pass_reads_a_ticket_changed_during_the_scan` |
| `PUT` writable fields only; unknown engineer/manager is 422 | sparse PUT of changed fields only; values validated first; refused values revert on the sheet and are logged | Tests: `test_sync_e2e`; **Live**: engineer reassign, status change, document set all accepted |
| (found live) a clear can be answered 200 and ignored; null is a 400 for documents | clears are sent alone (`""` first for documents, `null` for engineer), verified from the response, refused cleanly if impossible | Tests: `test_sync_e2e::test_clearing_a_document_works_whichever_blank...`; **Live**: document clear and engineer unassign both work |

## §6 The task

| Requirement | How | Evidence |
|---|---|---|
| 1. Pull every ticket into a real spreadsheet (Excel or Google Sheets), one row per ticket | `.xlsx` via openpyxl (default) or Google Sheets backend; the sheet is a real workbook with the required columns | **Live**: 976 rows + 31 on `Noise` = 1,007; opened and rendered in LibreOffice; Tests: `test_requirements::test_s4_noise_is_kept_off_the_board...` (every ticket accounted for) |
| 2. Push sheet edits (assign people, paste links, change status) | three-way merge per field against a stored baseline; sparse PUT after a fresh re-read | Tests: `test_sync_e2e`; **Live**: `deploy/live-check.sh` |
| Server-side changes sync in | same merge | Tests: `test_server_change_flows_into_the_sheet...` |
| Decide and document what happens when both sides changed | per field: **the API wins a true same-field conflict**, and the losing sheet value is logged on `Conflicts`; different fields both survive; `README.md` "Conflict policy" | Tests: `test_ticket_changed_on_both_sides_at_once...`, `test_same_field_conflict_api_wins...`; **Live**: "both sides, same field" passed (run 3) |
| An unchanged sheet cell never overwrites a fresh server change | the baseline comparison makes this a property of the algorithm; each pushed ticket is re-read just before the PUT; a cell edited *during* a sync is kept | Tests: `test_unchanged_sheet_cells_never_overwrite...`, `test_edit_made_during_the_sync_is_held...`, `test_lost_state_does_not_clobber...` |
| 3. Computed columns Stage, Action Owner, integrity flag; per-person summary | `Stage`, `Action Owner`, `Integrity` columns; `Summary` sheet | see §3 |
| 4. README: sync, conflict policy, API limits, noise/junk, assumptions, next steps | `README.md` (all six present) | read it |

## §7 The sheet contract

| Requirement | How | Evidence |
|---|---|---|
| The 11 required columns, named exactly | `board.TICKET_COLUMNS` (extras follow) | Test: `test_s7_required_columns_exist_with_exact_names` |
| `Status` is Open/Pending/Resolved/Closed; `Stage` one of the 7 values | | Test: `test_s7_status_is_one_of_the_four_labels_and_stage_one_of_the_seven` |
| `Engineer` is the exact roster name or blank; `Manager` as on the ticket; documents raw | served text is preserved exactly | Test: `test_s7_columns_equal_the_api_for_every_ticket` (every row, every column) |
| `sheet_cmd export <csv>`: current state, row 1 headers, displayed values | `sheet.py export`; values are written as values, so there is nothing to resolve | Tests: `test_export_and_apply_roundtrip_like_the_grader`, `test_grader_flow` |
| `sheet_cmd apply <csv>` (`Ticket ID,Column,Value`): type values like a human, **do not sync** | `sheet.py apply`; also refreshes Stage/Owner/Integrity locally, as a formula would | Tests: same, plus `test_apply_refreshes_stage_like_a_formula_would` |
| `submission.json` with `sync_cmd` and `sheet_cmd` | repo root | Test: `test_grader_flow::test_submission_json_names_the_two_commands` |
| `sync_cmd` performs one full two-way cycle and exits; env `FIELDOPS_BASE_URL` / `FIELDOPS_API_KEY` | `python3 sync.py` (exit 0; non-zero only on fatal failure); a missing package prints the install command | Test: `test_grader_flow::test_the_grader_scenario_end_to_end` drives the committed commands as a subprocess from the repo root |
| Noise may be left off the sheet | on a separate `Noise` sheet | see §4 |

## §8 What is looked at

Sync correctness, workflow logic, extraction and an honest write-up: covered above. "Clear, boring code": one module per concern (`client`, `merge`, `engine`, `workflow`, `extract`, `noise`, `backends/`), the merge and workflow are pure functions with their own tests.

## Not verified, and judgement calls

- **Google Sheets** has only been run against an in-memory fake of gspread, never live.
- **Real Excel** was not available; the workbook was opened and rendered in LibreOffice and read back with openpyxl.
- **Docker** was verified live on the VPS (build, run, HTTPS); the CI image build job has not run on GitHub.
- The grader's own Python needs `pip install -r requirements.txt` (`requests`, `openpyxl`); the commands print that instruction if a package is missing. All source is checked to parse on Python 3.9.
- **Judgement calls:** the API wins a same-field conflict (configurable: `CONFLICT_POLICY=sheet`); bill-chasing emails and quotations stay on the board as real work; Stage/Owner are stored values, not Excel formulas (they refresh on sync or `apply`, not while typing in Excel); `NA` must be exactly `NA`.
- **Not done (conscious cuts):** per-user accounts, push-based syncing (the API has no webhooks), per-field audit history beyond the `Conflicts` and `Activity` sheets.
