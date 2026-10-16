"""Tải trước những thứ app cần lúc chạy, để lần quét đầu tiên không phải chờ.

Chạy bởi CAI_DAT.bat: `python -m backend.prepare`. Chạy lại nhiều lần được: phần đã có thì bỏ qua.
"""
from __future__ import annotations

import os

from backend.collectors import browser_setup
from backend.core import config


def main() -> int:
    config.ensure_dirs()
    # Thư mục model không hỗ trợ symlink trên Windows thường; cảnh báo đó vô hại nên tắt cho đỡ rối mắt.
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    from faster_whisper.utils import download_model

    print("[1/2] Mô hình chép lời Whisper small (~490 MB, chỉ tải lần đầu)...", flush=True)
    # Cùng cache_dir với WhisperModel(download_root=data/models) trong lúc quét.
    download_model("small", cache_dir=str(config.DATA_DIR / "models"))
    print("      Xong.", flush=True)

    print("[2/2] Trình duyệt dùng để quét Facebook...", flush=True)
    if config.edge_path():
        print("      Dùng Microsoft Edge có sẵn trên máy.", flush=True)
    else:
        browser_setup.ensure_chromium()
        print("      Đã có Chromium.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
