"""Bổ sung chỉ số video và tải audio bằng yt-dlp như thư viện (PLAN §11.3).

yt-dlp là nguồn dự phòng: chỉ điền các trường còn trống, không ghi đè số đã lấy từ GraphQL.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

import yt_dlp
from yt_dlp.utils import YoutubeDLError

from backend.core import config
from backend.collectors.cookies import is_netscape_file
from backend.core.models import Video

logger = logging.getLogger(__name__)

_REEL_ID_RE = re.compile(r"facebook\.com/reel/(\d+)", re.IGNORECASE)
_PARTIAL_SUFFIXES = frozenset({".part", ".ytdl", ".temp"})
# Tải lần lượt từng video như người xem, kể cả khi pipeline phân tích nhiều video cùng lúc.
_DOWNLOAD_LOCK = threading.Lock()

# Trường của Video <- (khóa trong info của yt-dlp, kiểu). like_count không dùng:
# đó là số người thích, không phải tổng các loại cảm xúc (PLAN §11.3).
_FILL_FIELDS: dict[str, tuple[str, Callable]] = {
    "views": ("view_count", int),
    "comments": ("comment_count", int),
    "shares": ("repost_count", int),
    "posted_at": ("timestamp", int),
    "duration_s": ("duration", float),
    "caption": ("description", str),
}


def _to_watch_url(url: str) -> str:
    """Link /reel/<id> không hiện đủ bình luận; đổi sang /watch/?v=<id> (crawler-social ADR 0002)."""
    match = _REEL_ID_RE.search(url)
    if match is None:
        return url
    return f"https://m.facebook.com/watch/?v={match.group(1)}"


def _is_empty(value: object) -> bool:
    return value is None or value == ""


def _saved_header(path, pattern: str) -> str:
    """Đọc giá trị header đã lưu; bỏ qua nếu thiếu tệp hoặc nội dung lạ (không để chèn header)."""
    try:
        value = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return ""
    return value if re.fullmatch(pattern, value) else ""


def _cookie_opts() -> dict:
    """Cookie Netscape đã xuất từ profile trình duyệt của tool, kèm đúng User-Agent và ngôn ngữ của trình duyệt đó.

    Không đọc cookie của Chrome (PLAN §11.3). Cùng cookie nhưng khác UA trông như phiên bị đánh cắp,
    nên gửi UA và Accept-Language đã lưu khi quét/đăng nhập (thiếu thì yt-dlp dùng mặc định).
    """
    path = config.COOKIE_FILE
    if not path.exists():
        return {}
    if not is_netscape_file(path):
        logger.warning("Tệp cookie %s không đúng định dạng Netscape; bỏ qua cookie.", path)
        return {}
    opts: dict = {"cookiefile": str(path)}
    headers = {}
    user_agent = _saved_header(config.BROWSER_UA_FILE, r"[\x20-\x7e]{1,512}")
    if user_agent:
        headers["User-Agent"] = user_agent
    languages = _saved_header(config.BROWSER_LANG_FILE, r"[A-Za-z0-9,;=.\-]{1,200}")
    if languages:
        headers["Accept-Language"] = languages
    if headers:
        opts["http_headers"] = headers
    return opts


class _YdlLog:
    """Thông báo của yt-dlp đi vào logging (data/app.log), không in thẳng ra stdout/stderr.

    Lỗi cuối cùng được chỗ gọi ghi WARNING kèm lý do; ở đây chỉ giữ chi tiết ở mức INFO.
    """

    def debug(self, msg: str) -> None:  # yt-dlp gửi cả thông báo info qua debug
        pass

    def info(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        logger.info("yt-dlp: %s", msg)

    def error(self, msg: str) -> None:
        logger.info("yt-dlp: %s", msg)


# Chung cho mọi lượt gọi: không thanh tiến trình, không in ra console.
_QUIET_OPTS = {"quiet": True, "no_warnings": True, "noprogress": True, "logger": _YdlLog()}


def _with_account_fallback(run: Callable[[dict], object]) -> object:
    """Chạy yt-dlp không cookie trước (video công khai không cần tài khoản, tài khoản không bị dính
    vào lượt tải); chỉ khi lỗi mới thử lại bằng cookie của tài khoản phụ."""
    try:
        return run({})
    except YoutubeDLError:
        account = _cookie_opts()
        if not account:
            raise
        # YoutubeDL writes its cookie jar on exit. Give it a private snapshot so
        # a fallback cannot overwrite the scanner's newer, atomically exported jar.
        with tempfile.TemporaryDirectory(prefix='download_cookie_') as temporary:
            snapshot = Path(temporary) / 'cookies.txt'
            shutil.copyfile(account['cookiefile'], snapshot)
            return run({**account, 'cookiefile': str(snapshot),
                        'sleep_interval_requests': 1, 'sleep_interval': 2, 'max_sleep_interval': 6})


def fetch_metadata(url: str) -> dict:
    """Metadata của một video, không tải file.

    Trả về view_count, comment_count, repost_count, timestamp, duration, description.
    Khóa nào yt-dlp không có thì giá trị là None.
    """
    def run(extra: dict) -> dict:
        # Metadata can run for dozens of videos back to back; a 1 s request gap keeps the
        # anonymous IP from looking like a burst. Downloads are naturally paced by transcription.
        opts = {**_QUIET_OPTS, "skip_download": True, "noplaylist": True,
                "sleep_interval_requests": 1, **extra}
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(_to_watch_url(url), download=False) or {}

    info = _with_account_fallback(run)
    return {key: info.get(key) for key, _cast in _FILL_FIELDS.values()}


def fill_missing(video: Video) -> None:
    """Điền các trường còn trống (None hoặc chuỗi rỗng) từ yt-dlp. Không ghi đè giá trị đã có."""
    if not any(_is_empty(getattr(video, attr)) for attr in _FILL_FIELDS):
        return
    try:
        info = fetch_metadata(video.url)
    except YoutubeDLError as exc:
        logger.warning("yt-dlp không đọc được metadata của %s: %s", video.video_id, exc)
        return
    for attr, (key, cast) in _FILL_FIELDS.items():
        value = info.get(key)
        if _is_empty(getattr(video, attr)) and not _is_empty(value):
            setattr(video, attr, cast(value))


def _find_download(out_dir: Path, stem: str) -> Path | None:
    """File tải xong có tên bắt đầu bằng stem; bỏ file tạm .part và file rỗng."""
    candidates = sorted(
        path
        for path in out_dir.glob(f"{stem}.*")
        if path.is_file() and path.suffix.lower() not in _PARTIAL_SUFFIXES and path.stat().st_size > 0
    )
    return candidates[0] if candidates else None


def download_audio(url: str, out_dir: Path) -> Path | None:
    """Tải audio (bestaudio) vào out_dir.

    Coi là thành công khi có file đã tải xong, kể cả khi yt-dlp báo lỗi
    (ví dụ phụ đề hỏng; PLAN §11.5). Không có file thì trả None.
    Thử không cookie trước: trang Facebook khi đã đăng nhập có định dạng khác mà yt-dlp
    báo "Cannot parse data", còn reel công khai tải được không cần tài khoản.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    target = _to_watch_url(url)
    stem = "audio_" + hashlib.sha256(target.encode("utf-8")).hexdigest()[:16]

    def run(extra: dict) -> Path:
        opts = {
            **_QUIET_OPTS,
            # PyAV in the local transcriber can decode either audio or a combined stream.
            "format": "bestaudio/best",
            "outtmpl": os.path.join(str(out), f"{stem}.%(ext)s"),
            "noplaylist": True,
            # Anonymous public downloads are serialized; no account session to pace.
            # Account fallback retains the original request/download delays.
            **extra,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([target])
        except YoutubeDLError as exc:
            # yt-dlp có thể lỗi dù file đã có (ví dụ phụ đề hỏng); quyết định theo file.
            if _find_download(out, stem) is None:
                raise
            logger.warning("yt-dlp báo lỗi nhưng đã có audio (%s): %s", url, exc)
        found = _find_download(out, stem)
        if found is None:
            raise YoutubeDLError("không có file audio")
        return found

    with _DOWNLOAD_LOCK:
        try:
            return _with_account_fallback(run)
        except Exception as exc:  # noqa: BLE001 - mọi lỗi tải đều quy về "không có audio"
            logger.warning("Không tải được audio (%s): %s", url, exc)
    return None
