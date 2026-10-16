from copy import deepcopy
from datetime import datetime
import queue
import threading
import time
from types import SimpleNamespace

import pytest
from backend.api import scan, channels
from backend.services import pipeline


@pytest.fixture(autouse=True)
def fresh_session(monkeypatch):
    monkeypatch.setattr(scan, "_session", scan._new_session())
    monkeypatch.setattr(channels, "_logging_in", False)


def _event(**kwargs):
    values = dict(stage="scan", page_index=1, page_total=2, page_url="page", page_name="Kênh A",
                  message="Đang quét", done=False, error=None, step=0, steps=0,
                  transient=False, found=None, passed=None)
    values.update(kwargs)
    return SimpleNamespace(**values)


@pytest.fixture
def configured(monkeypatch):
    settings = {"terms_accepted_at": "2026-10-12", "scan": {"days": 14,
                "video_kinds": ["video", "reel"], "min_views": 50000,
                "viral_factor": 3, "max_per_channel": 10, "dedupe_threshold": 0.5}}
    saved = []
    monkeypatch.setattr(scan.config, "load_settings", lambda: deepcopy(settings))
    monkeypatch.setattr(scan.config, "save_settings", lambda value: saved.append(deepcopy(value)))
    monkeypatch.setattr(channels, "saved_channels", lambda: ["page", "second"])
    monkeypatch.setattr(scan.threading, "Thread", lambda **kwargs: SimpleNamespace(start=lambda: None))
    return settings, saved


def test_params_summary_and_persistence(configured):
    options = dict(days=30, video_kinds=["reel"], min_views=100000, viral_factor=4.5, max_per_channel=5)
    params = scan._params(options)
    assert params.formats == frozenset({"reel"})
    assert (params.days, params.min_views, params.viral_factor, params.max_per_channel) == (30, 100000, 4.5, 5)
    summary = scan.preview_scan(options)["summary"]
    assert "4.5× trung vị" in summary and "100.000" in summary and "5 video/kênh" in summary
    assert scan.start_scan(options)["ok"]
    saved = configured[1][0]["scan"]
    assert all(saved[name] == value for name, value in options.items())
    assert saved["dedupe_threshold"] == 0.5


@pytest.mark.parametrize("options,text", [
    ({"video_kinds": []}, "Chọn ít nhất"),
    ({"video_kinds": ["unknown"]}, "Loại video"),
    ({"days": 0}, "Số ngày"),
    ({"days": "bad"}, "số hợp lệ"),
    ({"min_views": -1}, "Lượt xem"),
    ({"viral_factor": 0}, "Hệ số"),
    ({"viral_factor": float("nan")}, "Hệ số"),
    ({"max_per_channel": 0}, "Số video"),
])
def test_invalid_options_block_start(configured, options, text):
    result = scan.preview_scan(options)
    assert not result["can_start"] and text in result["problems"][0]
    assert not scan.start_scan(options)["ok"]
    assert configured[1] == []


def test_terms_saved_once(configured, monkeypatch):
    settings, saved = configured
    settings.pop("terms_accepted_at")
    assert not scan.start_scan({})["ok"]
    assert not scan.preview_scan({})["can_start"]
    first = scan.accept_terms()["accepted_at"]
    assert datetime.fromisoformat(first).tzinfo is not None
    monkeypatch.setattr(scan.config, "load_settings", lambda: deepcopy(saved[-1]))
    assert scan.accept_terms()["accepted_at"] == first
    assert len(saved) == 1
    assert scan.get_scan_options()["terms"]["accepted_at"] == first


def test_options_read_saved_defaults(configured):
    options = scan.get_scan_options()
    assert options["defaults"] == {"days": 14, "video_kinds": ["video", "reel"],
        "min_views": 50000, "viral_factor": 3, "max_per_channel": 10}
    assert [item["id"] for item in options["kinds"]] == ["video", "reel"]
    assert options["terms"]["link"]["url"] == "https://www.facebook.com/terms"


def _enqueue(monkeypatch, events, **values):
    scan._session.update(running=True, scan_started=time.monotonic(), **values)
    for event in events:
        scan._session["scan_queue"].put(event)
    monkeypatch.setattr(scan, "redact", lambda value: value.replace("secret", "masked"))
    return scan._session


def _channel(url, **values):
    return dict(url=url, status="Chờ quét", found=None, passed=None, transcribed=0) | values


def test_explicit_channel_counts_and_transcription_progress(monkeypatch):
    state = _enqueue(monkeypatch, [
        _event(found=5, passed=2),
        _event(stage="transcribe", message="Xong video 1", step=1, steps=3),
        _event(stage="transcribe", message="Xong video 2", step=2, steps=3),
        _event(page_url="second", page_name="Kênh B", found=4, passed=1),
        _event(stage="transcribe", page_url="second", page_name="Kênh B", step=3, steps=3),
    ], scan_channels=[_channel("page"), _channel("second")])
    result = scan.get_scan_state()
    assert [(row["found"], row["passed"], row["transcribed"]) for row in result["channels"]] == [(5, 2, 2), (4, 1, 1)]
    assert all(row["progress"] == 1 for row in result["channels"])
    assert [lane["title"] for lane in result["lanes"]] == ["Quét Facebook", "Chép lời"]
    assert state["scan_transcribed"] == (3, 3)


def test_channel_unknown_distinct_from_zero():
    rows = scan._channel_rows([_channel("waiting"), _channel("empty", found=5, passed=0)])
    assert rows[0]["progress"] == 0 and rows[0]["passed"] is None
    assert rows[1]["progress"] == 1 and rows[1]["passed"] == 0


def test_lanes_keep_own_progress_and_countdown_not_logged(monkeypatch):
    _enqueue(monkeypatch, [
        _event(found=5, passed=2),
        _event(stage="transcribe", message="Đang chép lời", step=0, steps=2),
        _event(page_url="second", message="Nghỉ · còn 5 giây", transient=True),
    ], scan_channels=[_channel("page"), _channel("second")])
    result = scan.get_scan_state()
    first, second = result["lanes"]
    assert first["label"] == "1/2 kênh" and first["message"] == "Nghỉ · còn 5 giây"
    assert second["label"] == "0/2 video" and second["message"] == "Đang chép lời"
    assert len(result["log"]) == 2
    assert result["message"] == ""


def test_error_keeps_progress_and_masks(monkeypatch):
    prior = _event()
    _enqueue(monkeypatch, [_event(stage="error", message="Lỗi secret", error="secret")], progress=prior)
    result = scan.get_scan_state()
    assert scan._session["progress"] is prior
    assert result["errors"] == ["masked"] and "secret" not in result["log"][0]


def test_finished_freezes_elapsed_incremental_logs(monkeypatch):
    _enqueue(monkeypatch, [_event(stage="done", message="Xong", done=True), ("finished", None)])
    result = scan.get_scan_state()
    assert not result["running"] and result["overall"] == 1
    assert result["elapsed_s"] == scan.get_scan_state(1)["elapsed_s"]
    assert scan.get_scan_state(1)["log"] == []
    assert result["ended_without_result"]


def test_start_resets_previous_tracking(configured):
    scan._session.update(scan_overall=1, scan_log=["Cũ"], scan_transcribed=(9, 9))
    assert scan.start_scan({})["ok"]
    assert scan._session["scan_overall"] == 0 and scan._session["scan_log"] == []
    assert scan._session["scan_transcribed"] == (0, 0)
    assert all(row["found"] is None for row in scan._session["scan_channels"])


def test_stop_sets_cooperative_event(monkeypatch):
    _enqueue(monkeypatch, [])
    assert scan.stop_scan()["ok"]
    assert scan._session["stop_event"].is_set()
    assert scan.get_scan_state()["stopping"]


def test_worker_passes_pipeline_contract(monkeypatch, tmp_path):
    events, stop = queue.Queue(), threading.Event()
    params = pipeline.RunParams()
    path = tmp_path / "report.xlsx"
    def run(actual, settings=None, stop=None, on_progress=None):
        assert actual is params and settings == {"scan": {}}
        assert stop is sentinel
        on_progress(_event())
        return path
    sentinel = stop
    monkeypatch.setattr(pipeline, "run", run)
    scan._scan_worker(params, {"scan": {}}, events, stop)
    assert events.get_nowait().stage == "scan"
    assert events.get_nowait() == ("result", path)
    assert events.get_nowait()[0] == "finished"


def test_worker_failure_always_finishes(monkeypatch):
    events = queue.Queue()
    def failed(*args, **kwargs):
        raise RuntimeError("failure")
    monkeypatch.setattr(pipeline, "run", failed)
    monkeypatch.setattr(scan, "error_message", lambda exc: "Đã che lỗi")
    scan._scan_worker(pipeline.RunParams(), {}, events, threading.Event())
    assert events.get_nowait() == ("failure", "Đã che lỗi")
    assert events.get_nowait()[0] == "finished"


def test_running_login_and_empty_channels_block_start(configured, monkeypatch):
    scan._session["running"] = True
    assert not scan.start_scan({})["ok"]
    scan._session["running"] = False
    monkeypatch.setattr(channels, "is_logging_in", lambda: True)
    assert not scan.start_scan({})["ok"]
    monkeypatch.setattr(channels, "is_logging_in", lambda: False)
    monkeypatch.setattr(channels, "saved_channels", lambda: [])
    assert scan.start_scan({})["error"] == "Danh sách kênh trống. Vào Cài đặt để nhập các kênh cần quét."


def test_export_completes_channel_without_counting_reused_audio(monkeypatch):
    _enqueue(monkeypatch, [_event(stage="export", page_url="", message="Đang xuất Excel")],
             scan_channels=[_channel("page", found=10, passed=3, transcribed=1)])
    result = scan.get_scan_state()
    assert result["channels"][0]["progress"] == 1
    assert result["channels"][0]["transcribed"] == 1
    assert result["channels"][0]["status"] == "Hoàn tất"
    assert [lane["state"] for lane in result["lanes"]] == ["done", "done"]


def test_overlap_lane_not_finished_until_scanner_discovers_all_candidates(monkeypatch):
    _enqueue(monkeypatch, [
        _event(found=5, passed=1),
        _event(stage="transcribe", step=1, steps=1),
        _event(page_url="second", message="Đang quét kênh B"),
    ], scan_channels=[_channel("page"), _channel("second")])
    result = scan.get_scan_state()
    assert result["lanes"][1]["state"] == "current"
    assert result["channels"][0]["transcribed"] == 1
    _enqueue(monkeypatch, [_event(page_url="second", found=5, passed=2)])
    result = scan.get_scan_state()
    assert result["lanes"][1]["label"] == "1/3 video"
    _enqueue(monkeypatch, [
        _event(stage="transcribe", page_url="second", step=3, steps=3),
        _event(stage="enhance", page_url="second", step=3, steps=3),
    ])
    result = scan.get_scan_state()
    assert result["lanes"][1]["state"] == "current"
    assert result["lanes"][1]["label"] == "3/3 video"
