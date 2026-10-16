"""Giao diện JSON duy nhất được cung cấp cho JavaScript qua pywebview."""
from __future__ import annotations

import webbrowser
from urllib.parse import urlsplit

from backend.api import app_state, channels, common, logs, results, scan, llm


class Bridge:
    def __init__(self):
        self._window = None

    def attach(self, window):
        self._window = window

    # pywebview bỏ qua thuộc tính có cờ này; attach chỉ dành cho Python.
    attach._serializable = False

    def _call(self, function, *args):
        try:
            return function(*args)
        except Exception as exc:
            return {"ok": False, "error": common.error_message(exc)}

    def get_app_state(self):
        return self._call(app_state.get_app_state)

    def reset_configuration(self):
        return self._call(app_state.reset_configuration)

    def get_llm(self):
        return self._call(llm.get_llm)

    def connect_llm(self, key, base_url):
        return self._call(llm.connect_llm, key, base_url)

    def save_llm(self, key, base_url, model):
        return self._call(llm.save_llm, key, base_url, model)

    def remove_llm(self):
        return self._call(llm.remove_llm)

    def get_channels(self):
        return self._call(channels.get_channels)

    def save_channels(self, text):
        return self._call(channels.save_channels, text)

    def start_login(self):
        return self._call(channels.start_login)

    def get_login_state(self):
        return self._call(channels.get_login_state)

    def pick_cookie_file_and_import(self):
        return self._call(self._import_cookie_file)

    def _import_cookie_file(self):
        import webview

        paths = self._window.create_file_dialog(
            webview.FileDialog.OPEN,
            allow_multiple=False,
            file_types=("Tệp cookie (*.json;*.txt)",),
        )
        if not paths:
            return {"ok": True, "cancelled": True}
        return channels.import_cookies(paths[0])

    def get_logs(self, session, problems_only):
        return self._call(logs.get_logs, session, problems_only)

    def open_log_file(self, session):
        return self._call(logs.open_log_file, session)

    def get_scan_options(self):
        return self._call(scan.get_scan_options)

    def preview_scan(self, options):
        return self._call(scan.preview_scan, options)

    def accept_terms(self):
        return self._call(scan.accept_terms)

    def start_scan(self, options):
        return self._call(scan.start_scan, options)

    def stop_scan(self):
        return self._call(scan.stop_scan)

    def get_scan_state(self, log_since):
        return self._call(scan.get_scan_state, log_since)

    def list_results(self):
        return self._call(results.list_results)

    def get_result_summary(self, name):
        return self._call(results.get_result_summary, name)

    def delete_result(self, name):
        return self._call(results.delete_result, name)

    def open_result(self, name):
        return self._call(results.open_result, name)

    def open_output_folder(self):
        return self._call(results.open_output_folder)

    def save_result_as(self, name):
        return self._call(self._save_result_as, name)

    def _save_result_as(self, name):
        import webview

        paths = self._window.create_file_dialog(
            webview.FileDialog.SAVE,
            save_filename=name,
            file_types=("Bảng tính Excel (*.xlsx)",),
        )
        if not paths:
            return {"ok": True, "cancelled": True}
        return results.save_result_copy(name, paths[0])

    def open_url(self, url):
        return self._call(self._open_url, url)

    def _open_url(self, url):
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("Chỉ được mở liên kết http hoặc https hợp lệ.")
        if not webbrowser.open(url):
            raise RuntimeError("Không mở được trình duyệt mặc định.")
        return {"ok": True}
