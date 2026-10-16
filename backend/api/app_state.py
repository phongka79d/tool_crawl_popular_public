"""Computed setup journey and browser readiness for the desktop shell."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from backend.core import config
from backend.collectors import browser_setup
from backend.api import channels

logger = logging.getLogger("app.api.state")
_lock = threading.Lock()
_browser_ready = False
_browser_error: str | None = None


def prepare_browser() -> None:
    global _browser_ready, _browser_error
    try:
        if config.edge_path() is None:
            browser_setup.ensure_chromium()
    except Exception:
        logger.exception("Không chuẩn bị được trình duyệt quét")
        with _lock:
            _browser_ready = False
            _browser_error = "Không thể tải trình duyệt Chromium. Kiểm tra mạng, dung lượng ổ đĩa và mở lại ứng dụng."
    else:
        with _lock:
            _browser_ready = True
            _browser_error = None


@dataclass(frozen=True)
class _Guide:
    channel_count: int
    fb_ready: bool
    running: bool
    has_result: bool
    @property
    def setup_done(self) -> bool:
        return self.channel_count > 0 and self.fb_ready


def _journey(guide: _Guide) -> list[dict]:
    setup = "done" if guide.setup_done else "current"
    scan = "current" if guide.running or guide.setup_done and not guide.has_result else "done" if guide.has_result else "pending"
    result = "done" if guide.has_result else "pending"
    return [{"title": title, "state": state} for title, state in
            (("1 · Kênh & Facebook", setup), ("2 · Chạy quét", scan), ("3 · Kết quả", result))]

def _next_step(guide: _Guide) -> dict:
    if guide.running:
        text, page = "Đang quét và chép lời. Theo dõi tiến độ ở tab Chạy quét.", "scan"
    elif not guide.setup_done:
        todo = [text for text, done in (("thêm kênh cần quét", guide.channel_count > 0),
                                        ("đăng nhập Facebook", guide.fb_ready)) if not done]
        text, page = f"Hoàn tất Cài đặt: {' và '.join(todo)}.", "settings"
    elif guide.has_result:
        text, page = "Đã có file Excel mới. Xem thống kê và mở file ở tab Kết quả.", "results"
    else:
        text, page = "Sẵn sàng. Chọn số ngày và ngưỡng viral ở tab Chạy quét rồi bắt đầu.", "scan"
    return {"text": text, "page": page}


def reset_configuration() -> dict:
    from backend.api import scan
    with channels._lock:
        if channels.is_logging_in() or scan.is_running():
            return {"ok": False, "error": "Hãy chờ quét hoặc đăng nhập hoàn tất trước khi đặt lại."}
        from backend.core import keys
        keys.delete_key()
        config.save_settings(config.DEFAULT_SETTINGS)
        config.CHANNELS_FILE.parent.mkdir(parents=True, exist_ok=True)
        config.CHANNELS_FILE.write_text("", encoding="utf-8")
    return {"ok": True, "message": "Đã khôi phục cấu hình mặc định và xóa danh sách kênh."}


def get_app_state() -> dict:
    from backend.api import scan

    guide = _Guide(channel_count=len(channels.saved_channels()),
                   fb_ready=channels.facebook_logged_in(), running=scan.is_running(),
                   has_result=scan.has_result())
    logging_in = channels.is_logging_in()
    with _lock:
        browser = {"ready": _browser_ready, "error": _browser_error}
    return {"ok": True, "browser": browser,
            "guide": {"channel_count": guide.channel_count, "fb_ready": guide.fb_ready,
                      "running": guide.running, "has_result": guide.has_result, "setup_done": guide.setup_done},
            "journey": _journey(guide), "next_step": _next_step(guide),
            "logging_in": logging_in, "busy": guide.running or logging_in}
