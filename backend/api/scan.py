"""Phiên quét Facebook và chép lời cục bộ, đồng bộ bằng lock."""
from __future__ import annotations

import copy
import math
import queue
import threading
import time
from datetime import datetime
from pathlib import Path

from backend.core import config
from backend.services import pipeline
from backend.api import results
from backend.api.common import error_message, redact, fail

KINDS = (("video", "Video thường"), ("reel", "Reel"))
_lock = threading.Lock()


def _new_session():
    return dict(running=False, scan_queue=queue.Queue(), stop_event=threading.Event(),
                scan_started=None, scan_elapsed=0, scan_log=[], scan_errors=[], progress=None,
                scan_result=None, scan_channels=[], scan_overall=0.0, scan_lanes={},
                scan_transcribed=(0, 0))


_session = _new_session()


def _channel_rows(channels):
    rows = []
    for channel in channels:
        passed = channel["passed"]
        fraction = (0.6 + 0.4 * min(1, channel["transcribed"] / passed) if passed else
                    1.0 if passed == 0 else 0.1 if channel["status"] != "Chờ quét" else 0.0)
        if channel["status"] in ("Có lỗi", "Hoàn tất"):
            fraction = 1.0
        rows.append({**channel, "name": channel.get("name") or channel["url"], "progress": fraction})
    return rows


def _filter_summary(params):
    views = f"{params.min_views:,}".replace(",", ".")
    return (f"Trong {params.days} ngày: giữ video có lượt xem ≥ {params.viral_factor:g}× trung vị của kênh "
            f"VÀ ≥ {views}; tối đa {params.max_per_channel} video/kênh, ưu tiên lượt xem cao nhất.")


def _saved_video_kinds(saved):
    return [kind for kind, _ in KINDS if kind in (saved.get("video_kinds") or [])] or ["video", "reel"]


def _values(options, settings=None):
    saved = (settings if settings is not None else config.load_settings()).get("scan", {})
    try:
        return dict(days=int(options.get("days", saved.get("days", 14))),
                    formats=frozenset(options.get("video_kinds", _saved_video_kinds(saved))),
                    min_views=int(options.get("min_views", saved.get("min_views", 50000))),
                    viral_factor=float(options.get("viral_factor", saved.get("viral_factor", 3))),
                    max_per_channel=int(options.get("max_per_channel", saved.get("max_per_channel", 10))))
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("Các tùy chọn quét phải là số hợp lệ và danh sách loại video.") from exc


def _problems(values):
    problems = []
    if not values["formats"]:
        problems.append("Chọn ít nhất một loại video để quét.")
    elif not values["formats"] <= {kind for kind, _ in KINDS}:
        problems.append("Loại video không hợp lệ.")
    if values["days"] < 1:
        problems.append("Số ngày phải lớn hơn 0.")
    if values["min_views"] < 0:
        problems.append("Lượt xem tối thiểu không được âm.")
    if not math.isfinite(values["viral_factor"]) or values["viral_factor"] <= 0:
        problems.append("Hệ số viral phải lớn hơn 0.")
    if values["max_per_channel"] < 1:
        problems.append("Số video mỗi kênh phải lớn hơn 0.")
    return problems


def _params(options, settings=None):
    values = _values(options, settings)
    problems = _problems(values)
    if problems:
        raise ValueError(problems[0])
    return pipeline.RunParams(**values)


def get_scan_options():
    settings = config.load_settings()
    saved = settings.get("scan", {})
    defaults = {name: saved.get(name, value) for name, value in
                dict(days=14, min_views=50000, viral_factor=3, max_per_channel=10).items()}
    defaults["video_kinds"] = _saved_video_kinds(saved)
    return {"ok": True, "defaults": defaults,
            "kinds": [{"id": kind, "label": label} for kind, label in KINDS],
            "presets": {"days": [7, 14, 30]},
            "terms": {"accepted_at": settings.get("terms_accepted_at"), "paragraphs": [
                "Công cụ đọc Facebook qua trình duyệt đã đăng nhập (thu thập tự động).",
                "Điều khoản Facebook hạn chế thu thập tự động khi chưa được phép."], "bullets": [
                "Tài khoản có thể bị yêu cầu xác minh hoặc khóa. Nên dùng tài khoản phụ.",
                "Chỉ thu thập nội dung bạn được phép truy cập.", "Bạn tự chịu trách nhiệm khi sử dụng công cụ."],
                "link": {"label": "Điều khoản Facebook", "url": "https://www.facebook.com/terms"}}}


def preview_scan(options):
    settings = config.load_settings()
    try:
        values = _values(options, settings)
    except ValueError as exc:
        return {"ok": True, "summary": "", "problems": [str(exc)], "can_start": False}
    problems = _problems(values)
    summary = "" if problems else _filter_summary(pipeline.RunParams(**values))
    return {"ok": True, "summary": summary, "problems": problems,
            "can_start": not problems and bool(settings.get("terms_accepted_at")) and not is_running()}


def accept_terms():
    with _lock:
        settings = config.load_settings()
        accepted = settings.get("terms_accepted_at")
        if not accepted:
            accepted = datetime.now().astimezone().isoformat(timespec="seconds")
            settings["terms_accepted_at"] = accepted
            config.save_settings(settings)
        return {"ok": True, "accepted_at": accepted}


def _scan_worker(params, settings, events, stop):
    try:
        result = pipeline.run(params, settings=settings, stop=stop, on_progress=events.put)
        events.put(("result", result))
    except Exception as exc:
        events.put(("failure", error_message(exc)))
    finally:
        events.put(("finished", time.monotonic()))


def start_scan(options):
    from backend.api import channels
    with channels._lock, _lock:
        if channels.is_logging_in():
            return fail("Đang đăng nhập Facebook. Hãy hoàn tất đăng nhập trước khi quét.")
        _drain_scan_queue()
        if _session["running"]:
            return fail("Một lần quét đang chạy. Hãy dừng hoặc chờ hoàn tất.")
        settings = config.load_settings()
        if not settings.get("terms_accepted_at"):
            return fail("Vui lòng đọc và xác nhận lưu ý Facebook trước khi quét.")
        try:
            params = _params(options, settings)
        except ValueError as exc:
            return fail(str(exc))
        urls = channels.saved_channels()
        if not urls:
            return fail("Danh sách kênh trống. Vào Cài đặt để nhập các kênh cần quét.")
        settings.setdefault("scan", {}).update(days=params.days, video_kinds=sorted(params.formats),
            min_views=params.min_views, viral_factor=params.viral_factor, max_per_channel=params.max_per_channel)
        config.save_settings(settings)
        _session.clear()
        _session.update(_new_session())
        _session.update(running=True, scan_started=time.monotonic(), scan_channels=[
            dict(url=url, status="Chờ quét", found=None, passed=None, transcribed=0) for url in urls])
        worker = threading.Thread(target=_scan_worker,
            args=(params, copy.deepcopy(settings), _session["scan_queue"], _session["stop_event"]),
            daemon=True, name="video-scan")
        try:
            worker.start()
        except Exception:
            _session["running"] = False
            _session["scan_elapsed"] = time.monotonic() - _session["scan_started"]
            raise
        return {"ok": True}


def _track_channels(state, event):
    channels = state.setdefault("scan_channels", [])
    channel = next((row for row in channels if row["url"] == event.page_url), None)
    if channel is None and event.page_url:
        channel = dict(url=event.page_url, status="Chờ quét", found=None, passed=None, transcribed=0)
        channels.append(channel)
    if channel is not None:
        if event.page_name:
            channel["name"] = event.page_name
        if event.error:
            channel["status"] = "Có lỗi"
        elif event.stage == "scan":
            if channel["found"] is None:
                channel["status"] = "Đang quét"
            if event.found is not None:
                channel.update(found=event.found, passed=event.passed,
                               status="Đã chép lời" if event.passed == 0 else "Chờ chép lời")
        elif event.stage == "transcribe":
            channel["status"] = "Đang chép lời"
            previous, _ = state.get("scan_transcribed", (0, 0))
            if event.step > previous:
                channel["transcribed"] += event.step - previous
            if channel["passed"] is not None and channel["transcribed"] >= channel["passed"]:
                channel["status"] = "Đã chép lời"
    if event.stage == "transcribe" and event.steps:
        state["scan_transcribed"] = (event.step, event.steps)
    if event.stage in ("export", "done"):
        for row in channels:
            if row["status"] != "Có lỗi":
                row["status"] = "Hoàn tất"
    overall = 1.0 if event.done else 0.95 if event.stage == "export" else (
        0.05 + 0.85 * sum(row["progress"] for row in _channel_rows(channels)) / len(channels) if channels else 0.02)
    state["scan_overall"] = max(state.get("scan_overall", 0.0), overall)


def _record_scan_progress(state, event, now, redact):
    if event.message and not event.transient:
        state.setdefault("scan_log", []).append(f"{now:%H:%M:%S}  {redact(event.message)}")
    if event.error:
        state.setdefault("scan_errors", []).append(redact(event.error))
    else:
        state["progress"] = event
        if event.stage in ("scan", "transcribe", "enhance"):
            state.setdefault("scan_lanes", {})["transcribe" if event.stage == "enhance" else event.stage] = event
    _track_channels(state, event)


def _drain_scan_queue():
    while True:
        try:
            event = _session["scan_queue"].get_nowait()
        except queue.Empty:
            break
        if not isinstance(event, tuple):
            _record_scan_progress(_session, event, datetime.now(), redact)
            continue
        kind, value = event
        if kind == "result":
            _session["scan_result"] = str(value) if value else None
        elif kind == "failure":
            _session["scan_errors"].append(redact(value))
        elif kind == "finished":
            _session["running"] = False
            _session["scan_elapsed"] = max(0, (value if value is not None else time.monotonic()) - _session["scan_started"])


def stop_scan():
    with _lock:
        _drain_scan_queue()
        _session["stop_event"].set()
    return {"ok": True}


def _redacted(value):
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {key: _redacted(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redacted(item) for item in value]
    return value


def _lanes(state, stage):
    finished = stage in ("export", "done") or (state["scan_started"] is not None and not state["running"])
    channels = state["scan_channels"]
    scanned = sum(row["found"] is not None or row["status"] == "Có lỗi" for row in channels)
    total = len(channels)
    done, known = state["scan_transcribed"]
    lanes = []
    for name, title, completed, count, label in (("scan", "Quét Facebook", scanned, total, "kênh"),
                                               ("transcribe", "Chép lời", done, known, "video")):
        event = state["scan_lanes"].get(name)
        if event and event.stage == "enhance":
            completed, count, label = event.step, event.steps, "nhóm"
        complete = finished or count > 0 and completed >= count
        lanes.append(dict(id=name, title=title, state="done" if complete else "current" if event else "pending",
            message=event.message if event and not complete else "Đã hoàn tất." if complete else "Đang chờ bắt đầu.",
            page_url=event.page_url if event else None,
            fraction=completed / count if count else float(finished), label=f"{completed}/{count} {label}"))
    return lanes


def get_scan_state(log_since=0):
    with _lock:
        _drain_scan_queue()
        s = _session
        progress = s["progress"]
        stage = progress.stage if progress else None
        elapsed = time.monotonic() - s["scan_started"] if s["running"] else s["scan_elapsed"]
        result = s["scan_result"]
        if result:
            result = dict(name=Path(result).name, count=results.summary_count(Path(result)), elapsed_s=elapsed)
        return _redacted(dict(ok=True, running=s["running"], stopping=s["running"] and s["stop_event"].is_set(),
            elapsed_s=elapsed, item_label="video", overall=s["scan_overall"], stage=stage, lanes=_lanes(s, stage),
            message=progress.message if progress and stage not in ("scan", "transcribe") else "",
            channels=_channel_rows(s["scan_channels"]), log=s["scan_log"][max(0, int(log_since)):],
            log_total=len(s["scan_log"]), errors=list(dict.fromkeys(s["scan_errors"])), result=result,
            ended_without_result=s["scan_started"] is not None and not s["running"] and not result))


def is_running():
    with _lock:
        _drain_scan_queue()
        return _session["running"]


def has_result():
    with _lock:
        _drain_scan_queue()
        return bool(_session["scan_result"])


def clear_result(path):
    with _lock:
        _drain_scan_queue()
        if _session["scan_result"] and Path(_session["scan_result"]).resolve() == Path(path).resolve():
            _session["scan_result"] = None
