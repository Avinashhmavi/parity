import json
import threading
import time

import pytest

from fieldserve_board.config import ConfigError, Settings, load_dotenv
from fieldserve_board.locking import LockTimeout, file_lock
from fieldserve_board.state import State, StateStore


def test_state_roundtrip_and_atomic_file(tmp_path):
    store = StateStore(tmp_path / "s.json")
    state = State(baseline={"1": {"values": {"status": "Open"}}}, checkpoint="2026-01-01T00:00:00Z")
    store.save(state)
    assert store.load().baseline == state.baseline
    assert not list(tmp_path.glob(".state-*"))


def test_corrupt_state_is_set_aside_not_trusted_and_not_fatal(tmp_path):
    path = tmp_path / "s.json"
    path.write_text("{not json")
    assert StateStore(path).load().baseline == {}
    assert (tmp_path / "s.json.corrupt").exists()


def test_unknown_state_version_starts_fresh(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"version": 99, "baseline": {"1": {}}}))
    assert StateStore(path).load().baseline == {}


def test_lock_excludes_a_second_holder(tmp_path):
    path = tmp_path / "x.lock"
    order = []

    def second():
        with file_lock(path, timeout=5):
            order.append("second")

    with file_lock(path):
        t = threading.Thread(target=second)
        t.start()
        time.sleep(0.3)
        order.append("first")
    t.join()
    assert order == ["first", "second"]


def test_lock_times_out(tmp_path):
    path = tmp_path / "x.lock"
    # A second fd in the same process conflicts under flock semantics.
    with file_lock(path), pytest.raises(LockTimeout), file_lock(path, timeout=0.3, poll=0.05):
        pass


def test_settings_validate_choices_and_require_key():
    with pytest.raises(ConfigError):
        Settings.from_env({})
    with pytest.raises(ConfigError):
        Settings.from_env({"FIELDOPS_API_KEY": "k", "CONFLICT_POLICY": "coin-flip"})
    with pytest.raises(ConfigError):
        Settings.from_env({"FIELDOPS_API_KEY": "k", "BOARD_BACKEND": "numbers"})
    s = Settings.from_env({"FIELDOPS_API_KEY": "k", "FIELDOPS_BASE_URL": "http://x:1/"})
    assert s.base_url == "http://x:1" and s.requests_per_minute == 50 and s.conflict_policy == "api"


def test_dotenv_never_overrides_real_environment(tmp_path):
    env = tmp_path / ".env"
    env.write_text('# c\nFIELDOPS_API_KEY="from_file"\nOTHER=1\n')
    environ = {"FIELDOPS_API_KEY": "real"}
    load_dotenv(env, environ)
    assert environ == {"FIELDOPS_API_KEY": "real", "OTHER": "1"}
