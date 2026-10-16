from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.api import app_state, channels, common, logs
from backend.core import config
from backend.core.errors import ServiceError


@pytest.fixture(autouse=True)
def settings_environment(monkeypatch, tmp_path):
    directory = tmp_path / "config"
    directory.mkdir()
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(config, "CONFIG_DIR", directory)
    monkeypatch.setattr(config, "SETTINGS_FILE", directory / "settings.json")
    monkeypatch.setattr(config, "CHANNELS_FILE", directory / "channels.txt")
    monkeypatch.setattr(config, "COOKIE_FILE", tmp_path / "fb_cookies.txt")
    from backend.core import keys
    monkeypatch.setattr(keys, 'delete_key', lambda: None)
    config.save_settings(deepcopy(config.DEFAULT_SETTINGS))
    monkeypatch.setattr(channels, "_logging_in", False)
    from backend.api import scan
    monkeypatch.setattr(scan, "_session", scan._new_session())


def test_channels_save_preserves_comments_and_reload():
    text = "# Kênh ngành dược\nhttps://www.facebook.com/pharmacy.page\n\nhttps://www.facebook.com/another.page\n"
    result = channels.save_channels(text)
    expected = "# Kênh ngành dược\nhttps://www.facebook.com/pharmacy.page\nhttps://www.facebook.com/another.page\n"
    assert result["ok"] and result["count"] == 2
    assert config.CHANNELS_FILE.read_text(encoding="utf-8") == expected
    assert config.load_lines(config.CHANNELS_FILE) == [
        "https://www.facebook.com/pharmacy.page", "https://www.facebook.com/another.page"]
    assert channels.get_channels() == {"ok": True, "text": expected, "count": 2, "problems": []}
    assert channels.saved_channels() == config.load_lines(config.CHANNELS_FILE)


def test_channels_reject_group_without_writing():
    path = config.CHANNELS_FILE
    original = "# Giữ lại\nhttps://www.facebook.com/pharmacy.page\n"
    path.write_text(original, encoding="utf-8")
    result = channels.save_channels("https://www.facebook.com/groups/123456")
    assert not result["ok"] and result["problems"]
    assert path.read_text(encoding="utf-8") == original


def test_saved_channels_skip_invalid_and_comments():
    config.CHANNELS_FILE.write_text(
        "# note\nhttps://www.facebook.com/groups/123\nhttps://www.facebook.com/page\n", encoding="utf-8")
    assert channels.saved_channels() == ["https://www.facebook.com/page"]
    assert channels.get_channels()["problems"]


def test_reset_defaults_channels_preserves_data(tmp_path):
    config.COOKIE_FILE.write_text("session", encoding="utf-8")
    output = tmp_path / "kept.xlsx"
    output.write_bytes(b"result")
    config.CHANNELS_FILE.write_text("page", encoding="utf-8")
    settings = config.load_settings()
    settings["scan"]["days"] = 99
    config.save_settings(settings)
    assert app_state.reset_configuration()["ok"]
    assert config.load_settings() == config.DEFAULT_SETTINGS
    assert config.CHANNELS_FILE.read_text(encoding="utf-8") == ""
    assert config.COOKIE_FILE.read_text(encoding="utf-8") == "session"
    assert output.read_bytes() == b"result"


@pytest.mark.parametrize("count,ready,running,result,states,page", [
    (0, False, False, False, ["current", "pending", "pending"], "settings"),
    (1, True, False, False, ["done", "current", "pending"], "scan"),
    (1, True, True, False, ["done", "current", "pending"], "scan"),
    (1, True, False, True, ["done", "done", "done"], "results"),
])
def test_journey_next_step(count, ready, running, result, states, page):
    guide = app_state._Guide(count, ready, running, result)
    assert [step["state"] for step in app_state._journey(guide)] == states
    assert app_state._next_step(guide)["page"] == page


def test_app_state_combines_login_and_setup(monkeypatch):
    from backend.api import scan
    monkeypatch.setattr(channels, "saved_channels", lambda: ["page"])
    monkeypatch.setattr(channels, "facebook_logged_in", lambda: True)
    monkeypatch.setattr(channels, "is_logging_in", lambda: True)
    monkeypatch.setattr(scan, "is_running", lambda: False)
    monkeypatch.setattr(scan, "has_result", lambda: False)
    result = app_state.get_app_state()
    assert result["ok"] and result["busy"] and result["logging_in"]
    assert result["guide"]["setup_done"]


def test_prepare_browser_uses_edge_or_download_and_records_failures(monkeypatch):
    calls = []
    monkeypatch.setattr(config, "edge_path", lambda: "edge.exe")
    monkeypatch.setattr(app_state.browser_setup, "ensure_chromium", lambda: calls.append(True))
    app_state.prepare_browser()
    assert app_state._browser_ready and not calls
    monkeypatch.setattr(config, "edge_path", lambda: None)
    app_state.prepare_browser()
    assert app_state._browser_ready and calls == [True]

    def fail_download():
        raise OSError("offline")

    monkeypatch.setattr(app_state.browser_setup, "ensure_chromium", fail_download)
    app_state.prepare_browser()
    assert not app_state._browser_ready and app_state._browser_error


def test_get_logs_ordering_redaction_limit_and_sessions(monkeypatch, tmp_path):
    current, previous = tmp_path / "app.log", tmp_path / "app.prev.log"
    previous.write_text("previous", encoding="utf-8")
    monkeypatch.setattr(logs.applog, "LOG_FILE", current)
    monkeypatch.setattr(logs.applog, "PREVIOUS_LOG_FILE", previous)
    calls = []

    def records(problems_only, path):
        calls.append((problems_only, path))
        return [f"{index}: secret" for index in range(510)]

    monkeypatch.setattr(logs.applog, "read_records", records)
    monkeypatch.setattr(logs.applog, "redact", lambda value: value.replace("secret", "masked"))
    result = logs.get_logs("previous", False)
    assert result["ok"] and result["session"] == "previous"
    assert calls == [(False, previous)]
    assert [entry["id"] for entry in result["sessions"]] == ["current", "previous"]
    assert len(result["records"]) == 500
    assert result["records"][0] == "509: masked"
    assert result["records"][-1] == "10: masked"
    assert "secret" not in str(result)


def test_get_logs_missing_previous_falls_back_to_current(monkeypatch, tmp_path):
    monkeypatch.setattr(logs.applog, "LOG_FILE", tmp_path / "app.log")
    monkeypatch.setattr(logs.applog, "PREVIOUS_LOG_FILE", tmp_path / "absent.log")
    result = logs.get_logs("previous")
    assert result["session"] == "current" and result["records"] == []
    assert len(result["sessions"]) == 1


def test_redact_uses_session_protection(monkeypatch):
    protected = []
    monkeypatch.setattr(common.applog, "protect", lambda values: protected.extend(values))
    monkeypatch.setattr(common.applog, "redact", lambda text: text.replace("session-secret", "masked"))
    assert common.redact("session-secret", ("session-secret",)) == "masked"
    assert protected == ["session-secret"]


def test_error_message_redacts_expected_errors_and_hides_unexpected(monkeypatch):
    monkeypatch.setattr(common.applog, "redact", lambda text: text.replace("candidate-secret", "masked"))
    assert "candidate-secret" not in common.error_message(ServiceError("facebook", "candidate-secret"), ("candidate-secret",))
    assert "private detail" not in common.error_message(RuntimeError("private detail"))


def test_login_admission_prevents_duplicate_and_scan_overlap(monkeypatch):
    from backend.api import scan

    monkeypatch.setattr(channels, "_logging_in", False)
    monkeypatch.setattr(channels, "_message", None)
    monkeypatch.setattr(channels, "_notice", None)
    monkeypatch.setattr(scan, "is_running", lambda: True)
    assert not channels.start_login()["ok"]
    assert not channels.is_logging_in()
    monkeypatch.setattr(scan, "is_running", lambda: False)
    workers = []
    monkeypatch.setattr(channels.threading, "Thread", lambda **kwargs:
                        SimpleNamespace(start=lambda: workers.append(kwargs)))
    assert channels.start_login()["ok"]
    assert channels.is_logging_in()
    assert not channels.start_login()["ok"]
    assert len(workers) == 1 and workers[0]["daemon"] is True


def test_login_worker_publishes_notice_once(monkeypatch):
    monkeypatch.setattr(channels, "_logging_in", True)
    monkeypatch.setattr(channels, "_message", "old")
    monkeypatch.setattr(channels, "_notice", None)
    monkeypatch.setattr(channels.facebook, "login_interactive", lambda: True)
    monkeypatch.setattr(channels, "facebook_logged_in", lambda: True)
    channels._login_worker()
    first = channels.get_login_state()
    assert first["ok"] and first["fb_ready"] and not first["logging_in"]
    assert first["message"] is None and first["notice"]
    assert channels.get_login_state()["notice"] is None


def test_cookie_import_runs_off_calling_thread_and_keeps_source(monkeypatch, tmp_path):
    from backend.api import scan
    import threading

    monkeypatch.setattr(channels, "_logging_in", False)
    monkeypatch.setattr(scan, "is_running", lambda: False)
    path = tmp_path / "cookies.json"
    path.write_text("[]", encoding="utf-8")
    caller = threading.get_ident()
    calls = []

    def imported(source):
        calls.append((source, threading.get_ident()))
        return True

    monkeypatch.setattr(channels.facebook, "import_cookies", imported)
    assert channels.import_cookies(path)["ok"]
    assert calls[0][0] == path and calls[0][1] != caller
    assert path.exists() and not channels.is_logging_in()


def test_cookie_import_without_login_cookies_fails(monkeypatch, tmp_path):
    from backend.api import scan

    monkeypatch.setattr(channels, "_logging_in", False)
    monkeypatch.setattr(scan, "is_running", lambda: False)
    monkeypatch.setattr(channels.facebook, "import_cookies", lambda path: False)
    assert not channels.import_cookies(tmp_path / "empty.json")["ok"]
    assert not channels.is_logging_in()


def test_channels_write_error_does_not_claim_success(monkeypatch):
    def denied(path, *args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "write_text", denied)
    assert not channels.save_channels("https://www.facebook.com/page")["ok"]


def test_open_log_failure_returns_failure(monkeypatch):
    def denied(path):
        raise OSError("denied")

    monkeypatch.setattr(logs.os, "startfile", denied, raising=False)
    assert not logs.open_log_file("current")["ok"]
