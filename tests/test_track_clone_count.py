"""Tests for scripts/track_clone_count.py: pure logic, no network."""
import importlib.util
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

spec = importlib.util.spec_from_file_location(
    "track_clone_count", os.path.join(os.path.dirname(__file__), "..", "scripts", "track_clone_count.py")
)
tcc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tcc)


def _day(date, count):
    return {"timestamp": f"{date}T00:00:00Z", "count": count, "uniques": count // 3}


def test_fresh_state_accumulates():
    state = {"total": 0, "counted_dates": [], "since": "2026-09-21"}
    tcc.apply_new_days(state, {"clones": [_day("2026-09-07", 232), _day("2026-09-08", 225)]})
    assert state["total"] == 457
    assert state["counted_dates"] == ["2026-09-07", "2026-09-08"]


def test_overlapping_window_does_not_double_count():
    state = {"total": 457, "counted_dates": ["2026-09-07", "2026-09-08"], "since": "2026-09-21"}
    tcc.apply_new_days(state, {"clones": [_day("2026-09-07", 232), _day("2026-09-08", 225), _day("2026-09-09", 237)]})
    assert state["total"] == 457 + 237


def test_old_dates_are_trimmed_to_max_kept():
    state = {"total": 0, "counted_dates": [], "since": "2026-01-01"}
    days = [_day(f"2026-01-{d:02d}" if d <= 31 else f"2026-02-{d-31:02d}", 10) for d in range(1, 71)]
    tcc.apply_new_days(state, {"clones": days})
    assert len(state["counted_dates"]) == tcc.MAX_KEPT_DATES == 60
    assert state["total"] == 700


def test_missing_count_field_defaults_to_zero_not_crash():
    state = {"total": 5, "counted_dates": [], "since": "2026-09-21"}
    tcc.apply_new_days(state, {"clones": [{"timestamp": "2026-09-20T00:00:00Z"}]})
    assert state["total"] == 5


def test_empty_clones_list_is_a_noop():
    state = {"total": 10, "counted_dates": ["2026-09-01"], "since": "2026-09-21"}
    tcc.apply_new_days(state, {"clones": []})
    assert state["total"] == 10 and state["counted_dates"] == ["2026-09-01"]


def test_format_message_thresholds():
    assert tcc.format_message(0) == "0"
    assert tcc.format_message(42) == "42"
    assert tcc.format_message(999) == "999"
    assert tcc.format_message(1000) == "1.0k"
    assert tcc.format_message(4563) == "4.6k"
    assert tcc.format_message(1_250_000) == "1.2m"


def test_load_state_missing_file_returns_defaults():
    state = tcc.load_state("/nonexistent/path/for/testing.json")
    assert state["total"] == 0 and state["counted_dates"] == []
    assert "since" in state


def test_load_state_fills_missing_keys(tmp_path):
    p = tmp_path / "partial.json"
    p.write_text(json.dumps({"total": 99}))
    state = tcc.load_state(str(p))
    assert state["total"] == 99 and state["counted_dates"] == [] and "since" in state


def test_write_badge_roundtrip(tmp_path):
    p = tmp_path / "sub" / "badge.json"
    tcc.write_badge(str(p), 4563, "2026-09-21")
    badge = json.loads(p.read_text())
    assert badge["schemaVersion"] == 1
    assert badge["message"] == "4.6k"
    assert badge["label"] == "clones since 2026-09-21"
    assert badge["color"] == "blue"


def test_write_state_roundtrip(tmp_path):
    p = tmp_path / "sub" / "state.json"
    tcc.write_state(str(p), {"total": 7, "counted_dates": ["2026-09-01"], "since": "2026-09-01"})
    reloaded = json.loads(p.read_text())
    assert reloaded == {"total": 7, "counted_dates": ["2026-09-01"], "since": "2026-09-01"}


def test_main_without_token_is_a_graceful_noop(monkeypatch, tmp_path):
    monkeypatch.delenv("GH_TRAFFIC_TOKEN", raising=False)
    monkeypatch.setenv("STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setenv("BADGE_PATH", str(tmp_path / "badge.json"))
    assert tcc.main() == 0
    assert not (tmp_path / "state.json").exists()


def test_main_writes_badge_and_state_on_success(monkeypatch, tmp_path):
    monkeypatch.setenv("GH_TRAFFIC_TOKEN", "fake-token")
    monkeypatch.setenv("STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setenv("BADGE_PATH", str(tmp_path / "badge.json"))
    monkeypatch.setattr(tcc, "fetch_clones", lambda repo, token: {"clones": [_day("2026-09-20", 50)]})
    assert tcc.main() == 0
    state = json.loads((tmp_path / "state.json").read_text())
    badge = json.loads((tmp_path / "badge.json").read_text())
    assert state["total"] == 50
    assert badge["message"] == "50"


def test_main_api_failure_keeps_last_total_and_does_not_crash(monkeypatch, tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"total": 123, "counted_dates": ["2026-09-01"], "since": "2026-09-01"}))
    monkeypatch.setenv("GH_TRAFFIC_TOKEN", "fake-token")
    monkeypatch.setenv("STATE_PATH", str(state_path))
    monkeypatch.setenv("BADGE_PATH", str(tmp_path / "badge.json"))
    def boom(repo, token):
        raise ConnectionError("network down")
    monkeypatch.setattr(tcc, "fetch_clones", boom)
    assert tcc.main() == 0
    badge = json.loads((tmp_path / "badge.json").read_text())
    assert badge["message"] == "123"
