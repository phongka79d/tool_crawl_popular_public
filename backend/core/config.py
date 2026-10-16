"""Application paths and public scan defaults."""
from __future__ import annotations
import copy
import json
import os
import shutil
import sys
from pathlib import Path

_SOURCE_DIR = Path(__file__).resolve().parents[1]
ROOT = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", _SOURCE_DIR))
FRONTEND_DIR = BUNDLE_DIR / "frontend" if getattr(sys, "frozen", False) else ROOT / "frontend"
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"
PROFILE_DIR = ROOT / "profile"
DB_PATH = DATA_DIR / "cache.db"
COOKIE_FILE = DATA_DIR / "fb_cookies.txt"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
BROWSER_UA_FILE = DATA_DIR / "browser_ua.txt"
BROWSER_LANG_FILE = DATA_DIR / "browser_lang.txt"
DEFAULT_SETTINGS = {
    "llm": {"base_url": "", "model": ""},
    "scan": {"days": 14, "min_views": 50000, "viral_factor": 3,
             "max_per_channel": 10, "video_kinds": ["video", "reel"],
             "dedupe_threshold": 0.5, "delay_min_s": 3, "delay_max_s": 8,
             "page_delay_min_s": 30, "page_delay_max_s": 60,
             "max_videos_per_page": 200, "max_scroll_rounds": 60, "stall_rounds": 4},
}


def ensure_dirs() -> None:
    for directory in (DATA_DIR, OUTPUT_DIR, PROFILE_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def edge_path() -> str | None:
    for base in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        root = os.environ.get(base)
        if root:
            exe = Path(root) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if exe.is_file():
                return str(exe)
    return shutil.which("msedge")


def load_json(name: str) -> dict:
    return json.loads((CONFIG_DIR / name).read_text(encoding="utf-8"))


def load_settings() -> dict:
    result = copy.deepcopy(DEFAULT_SETTINGS)
    if SETTINGS_FILE.exists():
        stored = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        result["scan"].update({key: value for key, value in stored.get("scan", {}).items()
                               if key in result["scan"]})
        result["llm"].update({key: value for key, value in stored.get("llm", {}).items()
                              if key in result["llm"]})
        if "terms_accepted_at" in stored:
            result["terms_accepted_at"] = stored["terms_accepted_at"]
    return result


def save_settings(settings: dict) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_lines(rel_path: str) -> list[str]:
    path = ROOT / rel_path
    if not path.exists():
        return []
    return [line for raw in path.read_text(encoding="utf-8").splitlines()
            if (line := raw.strip()) and not line.startswith("#")]
