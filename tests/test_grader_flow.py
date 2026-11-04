"""Drive the repo exactly as the grader does: ``submission.json`` commands, run
from the repo root, with FIELDOPS_BASE_URL / FIELDOPS_API_KEY in the environment."""

from __future__ import annotations

import csv
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

from tests.conftest import KEY

ROOT = Path(__file__).resolve().parent.parent
SUBMISSION = json.loads((ROOT / "submission.json").read_text())


def run(cmd: str, *args: str, env: dict) -> subprocess.CompletedProcess:
    parts = shlex.split(cmd)
    assert parts[0] == "python3"
    return subprocess.run([sys.executable, *parts[1:], *args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)


def read_csv(path: Path) -> dict:
    with open(path, newline="", encoding="utf-8") as fh:
        return {int(r["Ticket ID"]): r for r in csv.DictReader(fh)}


def test_submission_json_names_the_two_commands():
    assert set(SUBMISSION) == {"sync_cmd", "sheet_cmd"}
    assert SUBMISSION["sync_cmd"] == "python3 sync.py" and SUBMISSION["sheet_cmd"] == "python3 sheet.py"


def test_the_grader_scenario_end_to_end(api, tmp_path):
    env = {
        **os.environ,
        "FIELDOPS_BASE_URL": api.url,
        "FIELDOPS_API_KEY": KEY,
        "BOARD_XLSX_PATH": str(tmp_path / "board.xlsx"),
        "BOARD_STATE_PATH": str(tmp_path / "state.json"),
        "API_REQUESTS_PER_MINUTE": "100000",
        "NO_PROXY": "127.0.0.1",
        "no_proxy": "127.0.0.1",
    }
    sync, sheet = SUBMISSION["sync_cmd"], SUBMISSION["sheet_cmd"]

    first = run(sync, env=env)
    assert first.returncode == 0, first.stderr
    summary = json.loads(first.stdout.strip().splitlines()[-1])
    assert summary["ok"] and summary["tickets_seen"] == len(api.state.tickets)

    # 1. scripted changes on the API side, sync, diff the CSV export
    ids = sorted(i for i, t in api.state.tickets.items() if "OMNIMART" in t["subject"])
    a, b, c = ids[0], ids[1], ids[2]
    api.put(a, status=4, work_report="")
    api.put(b, manager="Dev Malhotra", engineer_id=7)
    api.put(c, invoice="NA", purchase_order="https://files.fieldserve.example/po/new.pdf")
    assert run(sync, env=env).returncode == 0
    out = tmp_path / "out.csv"
    assert run(sheet, "export", str(out), env=env).returncode == 0
    rows = read_csv(out)
    assert rows[a]["Status"] == "Resolved" and "Resolved without Work Report" in rows[a]["Integrity"]
    assert rows[b]["Manager"] == "Dev Malhotra" and rows[b]["Engineer"] == "Gita Nair"
    assert rows[c]["Invoice"] == "NA" and rows[c]["Purchase Order"].endswith("new.pdf")

    # 2. cell edits through sheet.py apply, a simultaneous server change, sync, check the API
    edits = tmp_path / "edits.csv"
    edits.write_text(
        "Ticket ID,Column,Value\n"
        f"{a},Engineer,Esha Pillai\n"
        f"{a},Work Report,https://files.fieldserve.example/wr/{a}.pdf\n"
        f"{b},Status,Closed\n",
        encoding="utf-8",
    )
    assert run(sheet, "apply", str(edits), env=env).returncode == 0
    api.put(b, status=3)  # same field changed on the server meanwhile
    api.put(a, manager="Chitra Menon")  # different field on a: both must survive
    done = run(sync, env=env)
    assert done.returncode == 0, done.stderr

    ta, tb = api.ticket(a), api.ticket(b)
    assert ta["engineer_id"] == 5 and ta["work_report"].endswith(f"{a}.pdf") and ta["manager"] == "Chitra Menon"
    assert tb["status"] == 3  # the fresh server change was not overwritten by the stale sheet cell
    assert run(sheet, "export", str(out), env=env).returncode == 0
    rows = read_csv(out)
    assert rows[a]["Engineer"] == "Esha Pillai" and rows[a]["Manager"] == "Chitra Menon"
    assert rows[b]["Status"] == "Pending"


def test_missing_key_is_a_clean_failure_not_a_traceback(tmp_path):
    # An explicit empty value also stops a developer's local .env from supplying a key.
    env = {**os.environ, "FIELDOPS_API_KEY": ""}
    env["BOARD_XLSX_PATH"] = str(tmp_path / "b.xlsx")
    env["BOARD_STATE_PATH"] = str(tmp_path / "s.json")
    result = run("python3 sync.py", env={**env, "HOME": str(tmp_path)})
    assert result.returncode == 2 and "FIELDOPS_API_KEY" in result.stderr and "Traceback" not in result.stderr
