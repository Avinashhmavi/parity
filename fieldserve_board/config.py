"""Settings, read once from the environment (and an optional ``.env`` file)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE_URL = "http://13.233.55.184:8377"


class ConfigError(RuntimeError):
    pass


def load_dotenv(path: Path, environ: Optional[dict] = None) -> None:
    """Minimal ``.env`` loader: ``KEY=value`` lines, never overrides real env."""
    environ = os.environ if environ is None else environ
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        environ.setdefault(key, value)


@dataclass(frozen=True)
class Settings:
    base_url: str
    api_key: str
    backend: str  # "xlsx" or "gsheets"
    xlsx_path: Path
    state_path: Path
    conflict_policy: str  # "api" or "sheet"
    trusted_domains: tuple
    requests_per_minute: int
    http_timeout: float
    google_sheet_id: str
    google_credentials: str
    sync_interval_seconds: int
    access_user: str = "board"
    access_password: str = ""

    @classmethod
    def from_env(cls, environ: Optional[Mapping[str, str]] = None, *, require_key: bool = True) -> Settings:
        if environ is None:
            load_dotenv(REPO_ROOT / ".env")
            environ = os.environ
        get = environ.get

        api_key = (get("FIELDOPS_API_KEY") or "").strip()
        if require_key and not api_key:
            raise ConfigError("FIELDOPS_API_KEY is not set (see .env.example)")

        backend = (get("BOARD_BACKEND") or "xlsx").strip().lower()
        if backend not in ("xlsx", "gsheets"):
            raise ConfigError("BOARD_BACKEND must be 'xlsx' or 'gsheets'")
        policy = (get("CONFLICT_POLICY") or "api").strip().lower()
        if policy not in ("api", "sheet"):
            raise ConfigError("CONFLICT_POLICY must be 'api' or 'sheet'")

        def path(name: str, default: str) -> Path:
            p = Path(get(name) or default).expanduser()
            return p if p.is_absolute() else REPO_ROOT / p

        return cls(
            base_url=(get("FIELDOPS_BASE_URL") or DEFAULT_BASE_URL).rstrip("/"),
            api_key=api_key,
            backend=backend,
            xlsx_path=path("BOARD_XLSX_PATH", "data/FieldServe_Board.xlsx"),
            state_path=path("BOARD_STATE_PATH", "data/sync_state.json"),
            conflict_policy=policy,
            trusted_domains=tuple(
                d.strip().lower() for d in (get("TRUSTED_EMAIL_DOMAINS") or "omnimart.example").split(",") if d.strip()
            ),
            # The server allows 60/min; stay under it so we never trip the
            # "hammering resets the window" behaviour.
            requests_per_minute=int(get("API_REQUESTS_PER_MINUTE") or 55),
            http_timeout=float(get("API_TIMEOUT_SECONDS") or 20),
            google_sheet_id=(get("GOOGLE_SHEET_ID") or "").strip(),
            google_credentials=(get("GOOGLE_SERVICE_ACCOUNT") or "").strip(),
            sync_interval_seconds=int(get("SYNC_INTERVAL_SECONDS") or 0),
            access_user=(get("BOARD_USER") or "board").strip(),
            access_password=get("BOARD_PASSWORD") or "",
        )
