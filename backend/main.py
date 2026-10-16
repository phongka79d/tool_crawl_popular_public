"""Điểm vào cửa sổ Windows của Video Công Thức."""
from __future__ import annotations

import socket
import shutil
import sys
import threading
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core import applog, config


# pywebview mặc định dùng cổng 42001 cho mọi app; app pywebview khác đang giữ cổng đó thì cửa sổ
# này sẽ hiện nhầm giao diện của app kia. Dùng cổng riêng, cố định để giữ localStorage giữa các lần mở;
# khác cổng 47231 của bản đầy đủ Video Công Thức để chạy song song hai bản không bị trùng.
PREFERRED_HTTP_PORT = 47241


class WebViewUnavailable(RuntimeError):
    """Không khởi động được bộ máy hiển thị Edge WebView2."""


def _port_free(port: int) -> bool:
    """Thử bind độc quyền: trên Windows SO_EXCLUSIVEADDRUSE không cho dùng chung cổng đang có app nghe."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def http_port(preferred: int = PREFERRED_HTTP_PORT) -> int:
    """Cổng máy chủ giao diện: cổng riêng của app nếu trống, không thì một cổng trống do hệ điều hành cấp.

    Đổi cổng chỉ làm mất trang đang mở và cờ chào mừng lưu trong localStorage, không mất dữ liệu.
    """
    if _port_free(preferred):
        return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    applog.log.warning("Cổng giao diện %s đang bị ứng dụng khác dùng; chuyển sang cổng %s.", preferred, port)
    return port


def _show_fatal_error(exc: BaseException) -> None:
    import ctypes

    if isinstance(exc, WebViewUnavailable):
        message = (
            "Không khởi động được Microsoft Edge WebView2.\n\n"
            "Hãy cài Microsoft Edge WebView2 Runtime rồi mở lại Video Công Thức:\n"
            "https://developer.microsoft.com/microsoft-edge/webview2/\n\n"
            f"{exc}\n\nChi tiết trong data\\app.log."
        )
    else:
        message = (
            "Video Công Thức không khởi động được.\n\n"
            f"{type(exc).__name__}: {exc}\n\nChi tiết trong data\\app.log."
        )
    ctypes.windll.user32.MessageBoxW(None, message, "Video Công Thức", 0x10)


def _drop_stale_ui_cache(storage: Path) -> None:
    """Xoá cache HTTP của WebView2 để giao diện luôn là bản mới nhất sau khi cập nhật.

    Máy chủ của pywebview không gửi Cache-Control (bottle.static_file bỏ header đặt trước),
    nên WebView2 tự giữ JS/CSS cũ. Chỉ xoá cache; localStorage và phiên đăng nhập giữ nguyên.
    """
    for name in ("Cache", "Code Cache"):
        shutil.rmtree(storage / "EBWebView" / "Default" / name, ignore_errors=True)


def _serve() -> None:
    import webview

    from backend.api import Bridge, app_state, scan

    threading.Thread(target=app_state.prepare_browser, daemon=True, name="prepare-browser").start()
    _drop_stale_ui_cache(config.DATA_DIR / "webview")
    bridge = Bridge()
    window = webview.create_window(
        "Video Công Thức",
        url=str(config.FRONTEND_DIR / "index.html"),
        js_api=bridge,
        width=1280,
        height=860,
        min_size=(1100, 720),
        background_color="#F6F7FB",
    )
    if window is None:
        raise RuntimeError("Không tạo được cửa sổ ứng dụng.")
    bridge.attach(window)

    def on_closing():
        try:
            if scan.get_scan_state(0).get("running"):
                if not window.create_confirmation_dialog(
                    "Video Công Thức", "Đang quét. Đóng ứng dụng sẽ dừng quét. Vẫn đóng?"
                ):
                    return False
                scan.stop_scan()
            return True
        except Exception:
            applog.log.exception("Không kiểm tra hoặc dừng được phiên quét khi đóng cửa sổ")
            return False

    window.events.closing += on_closing
    renderer_errors = []

    def check_renderer():
        # pywebview 6.2.1 có thể âm thầm dùng MSHTML khi máy thiếu WebView2.
        if webview.renderer != "edgechromium":
            renderer_errors.append(WebViewUnavailable("Máy chưa có bộ máy hiển thị Edge WebView2 phù hợp."))
            window.destroy()

    try:
        webview.start(
            check_renderer,
            gui="edgechromium",
            debug=False,
            private_mode=False,
            storage_path=str(config.DATA_DIR / "webview"),
            http_port=http_port(),
            icon=str(config.FRONTEND_DIR / "img" / "logo.ico"),
        )
    except Exception as exc:
        raise WebViewUnavailable(str(exc)) from exc
    if renderer_errors:
        raise renderer_errors[0]


def main() -> None:
    try:
        applog.setup()
        config.ensure_dirs()
        _serve()
    except Exception as exc:
        applog.log.exception("Không khởi động được ứng dụng")
        _show_fatal_error(exc)
        raise


if __name__ == "__main__":
    main()
