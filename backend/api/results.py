"""Thư viện Excel và thống kê thuần JSON cho ứng dụng desktop."""
from __future__ import annotations

import copy
import os
import shutil
import threading
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

from backend.core import config
from backend.services import export_excel
from backend.api.common import fail

_CACHE_LIMIT = 64
_cache = OrderedDict()
_cache_lock = threading.Lock()


def _safe_excel_path(path: Path, output_dir: Path) -> Path:
    root, target = output_dir.resolve(), path.resolve()
    if target.parent != root or target.suffix.lower() != ".xlsx":
        raise ValueError("Chỉ được chọn file Excel trong thư mục kết quả.")
    return target


def _named_path(name: str) -> Path:
    if not isinstance(name, str) or not name or any(c in name for c in '/\\:') or Path(name).name != name:
        raise ValueError("Tên file Excel không hợp lệ.")
    return _safe_excel_path(config.OUTPUT_DIR / name, config.OUTPUT_DIR)


def _cached_summary(path: str, mtime: int) -> dict:
    key = (path, mtime)
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return copy.deepcopy(_cache[key])
    summary = export_excel.read_summary(Path(path))
    with _cache_lock:
        _cache[key] = copy.deepcopy(summary)
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_LIMIT:
            _cache.popitem(last=False)
    return summary


def _file_summary(path: Path) -> dict:
    try:
        path = path.resolve()
        return _cached_summary(str(path), path.stat().st_mtime_ns)
    except OSError:
        return {}


def summary_count(path: Path) -> int | None:
    return _file_summary(Path(path)).get("total")


def list_results() -> dict:
    files = []
    for path in config.OUTPUT_DIR.glob("*"):
        try:
            if path.suffix.lower() != ".xlsx" or not path.is_file():
                continue
            _named_path(path.name)
            stat = path.stat()
        except (OSError, ValueError):
            continue
        size = (f"{stat.st_size / 1024:.0f} KB" if stat.st_size < 1024 * 1024 else
                f"{stat.st_size / (1024 * 1024):.1f} MB".replace(".", ","))
        files.append({"name": path.name, "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m/%Y %H:%M"),
                      "modified_ts": stat.st_mtime, "size_text": size})
    return {"ok": True, "folder": str(config.OUTPUT_DIR),
            "files": sorted(files, key=lambda item: item["modified_ts"], reverse=True)}


def get_result_summary(name: str) -> dict:
    try:
        path = _named_path(name)
    except ValueError as exc:
        return fail(str(exc))
    try:
        return {"ok": True, "summary": _file_summary(path) or None}
    except ValueError as exc:
        return fail(str(exc))


def _delete_excel(path: Path, output_dir: Path) -> Path:
    target = _safe_excel_path(path, output_dir)
    target.unlink()
    return target


def delete_result(name: str) -> dict:
    try:
        target = _named_path(name)
        _delete_excel(target, config.OUTPUT_DIR)
    except PermissionError:
        return fail("Không xóa được vì file đang mở hoặc bị khóa. Đóng file trong Excel rồi thử lại.")
    except (OSError, ValueError):
        return fail("Không thể xóa file. Kiểm tra vị trí file và quyền truy cập thư mục kết quả.")
    with _cache_lock:
        for key in list(_cache):
            if key[0] == str(target):
                del _cache[key]
    from backend.api import scan
    scan.clear_result(target)
    return {"ok": True, "message": f"Đã xóa file {name}."}


def open_result(name: str) -> dict:
    try:
        path = _named_path(name)
        if not path.is_file():
            return fail("Không tìm thấy file Excel đã chọn.")
        os.startfile(path)
    except (OSError, AttributeError, ValueError):
        return fail("Không thể mở file Excel trên máy này.")
    return {"ok": True}


def open_output_folder() -> dict:
    try:
        os.startfile(config.OUTPUT_DIR)
    except (OSError, AttributeError):
        return fail("Không thể mở thư mục kết quả trên máy này.")
    return {"ok": True}


def save_result_copy(name: str, dest: str) -> dict:
    try:
        source, target = _named_path(name), Path(dest).resolve()
        if source == target:
            return fail("Hãy chọn vị trí khác với file Excel gốc.")
        shutil.copy2(source, target)
    except (OSError, ValueError):
        return fail("Không thể lưu bản sao Excel. Kiểm tra vị trí và quyền ghi file.")
    return {"ok": True, "message": "Đã lưu bản sao Excel."}
