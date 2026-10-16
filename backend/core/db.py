"""SQLite metadata, transcript cache, exported-content history and run logs.

Connection and upsert patterns adapted from Vyral Forge (MIT).
"""
from __future__ import annotations
import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import fields
from pathlib import Path
from backend.core import config
from backend.core.models import Page, Video

_VIDEO_COLUMNS = {
    "video_id": "TEXT PRIMARY KEY", "url": "TEXT", "page_url": "TEXT", "page_name": "TEXT",
    "page_followers": "INTEGER", "posted_at": "INTEGER", "format": "TEXT",
    "is_live": "INTEGER NOT NULL DEFAULT 0", "duration_s": "REAL", "views": "INTEGER",
    "reactions": "INTEGER", "comments": "INTEGER", "shares": "INTEGER", "caption": "TEXT",
    "transcript": "TEXT", "transcript_status": "TEXT", "transcript_language": "TEXT",
    "updated_at": "INTEGER",
}
SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (url TEXT PRIMARY KEY, name TEXT, followers INTEGER, last_scanned_at INTEGER);
CREATE TABLE IF NOT EXISTS videos (%s);
CREATE INDEX IF NOT EXISTS idx_videos_page ON videos(page_url);
CREATE INDEX IF NOT EXISTS idx_videos_posted ON videos(posted_at);
CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY AUTOINCREMENT, started_at INTEGER,
    finished_at INTEGER, params_json TEXT, log_json TEXT);
CREATE TABLE IF NOT EXISTS taken (video_id TEXT PRIMARY KEY, url TEXT, page_name TEXT,
    views INTEGER, posted_at INTEGER, transcript TEXT, taken_on TEXT, transcript_clean TEXT,
    status TEXT NOT NULL CHECK(status IN ('taken','duplicate_script','no_speech')));
""" % ", ".join(f"{name} {kind}" for name, kind in _VIDEO_COLUMNS.items())


@contextmanager
def conn(path: str | Path | None = None):
    target = Path(path) if path is not None else Path(config.DB_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_db(path=None) -> None:
    with conn(path) as c:
        c.executescript(SCHEMA)
        columns = {row['name'] for row in c.execute('PRAGMA table_info(videos)')}
        for name, kind in _VIDEO_COLUMNS.items():
            if name not in columns:
                c.execute(f'ALTER TABLE videos ADD COLUMN {name} {kind}')
        taken_columns = {row['name'] for row in c.execute('PRAGMA table_info(taken)')}
        if 'transcript_clean' not in taken_columns:
            c.execute('ALTER TABLE taken ADD COLUMN transcript_clean TEXT')


def upsert_page(page: Page, path=None) -> None:
    with conn(path) as c:
        c.execute('''INSERT INTO pages VALUES (?,?,?,?) ON CONFLICT(url) DO UPDATE SET
            name=COALESCE(NULLIF(excluded.name,''),pages.name),
            followers=COALESCE(excluded.followers,pages.followers), last_scanned_at=excluded.last_scanned_at''',
                  (page.url, page.name, page.followers, int(time.time())))


def upsert_video(video: Video, path=None) -> None:
    values = {name: getattr(video, name) for name in _VIDEO_COLUMNS if name != 'updated_at'}
    values['is_live'] = int(video.is_live)
    values['updated_at'] = int(time.time())
    updates = []
    for name in values:
        if name == 'video_id':
            continue
        if name == 'transcript_status':
            updates.append("transcript_status=CASE WHEN NULLIF(excluded.transcript,'') IS NOT NULL OR NULLIF(videos.transcript,'') IS NULL THEN COALESCE(NULLIF(excluded.transcript_status,''),videos.transcript_status) ELSE videos.transcript_status END")
        elif name == 'is_live':
            updates.append('is_live=MAX(videos.is_live,excluded.is_live)')
        else:
            updates.append(f"{name}=COALESCE(NULLIF(excluded.{name},''),videos.{name})")
    with conn(path) as c:
        c.execute(f"INSERT INTO videos ({','.join(values)}) VALUES ({','.join(':'+k for k in values)}) ON CONFLICT(video_id) DO UPDATE SET {','.join(updates)}", values)


def get_video(video_id: str, path=None) -> Video | None:
    with conn(path) as c:
        row = c.execute('SELECT * FROM videos WHERE video_id=?', (video_id,)).fetchone()
    if row is None:
        return None
    data = {field.name: row[field.name] for field in fields(Video) if field.name in row.keys() and row[field.name] is not None}
    for required in ('url', 'page_url'):
        data.setdefault(required, '')
    data['is_live'] = bool(data.get('is_live'))
    return Video(**data)


def get_transcript(video_id: str, path=None) -> tuple[str, str] | None:
    video = get_video(video_id, path)
    return (video.transcript, video.transcript_status) if video and (video.transcript or video.transcript_status) else None


def save_transcript(video_id: str, text: str, status: str, path=None, transcript_language: str = 'vi') -> None:
    upsert_video(Video(video_id, '', '', transcript=text, transcript_status=status,
                       transcript_language=transcript_language), path)


def get_taken(video_id: str, path=None) -> dict | None:
    with conn(path) as c:
        row = c.execute('SELECT * FROM taken WHERE video_id=?', (video_id,)).fetchone()
    return dict(row) if row else None


def list_taken(path=None) -> list[dict]:
    with conn(path) as c:
        return [dict(row) for row in c.execute("SELECT * FROM taken WHERE status='taken' ORDER BY taken_on,video_id")]


def save_taken(video: Video, status: str, taken_on: str, path=None) -> None:
    with conn(path) as c:
        c.execute('''INSERT INTO taken
            (video_id,url,page_name,views,posted_at,transcript,taken_on,status,transcript_clean)
            VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(video_id) DO UPDATE SET
            url=excluded.url,page_name=excluded.page_name,views=excluded.views,posted_at=excluded.posted_at,
            transcript=excluded.transcript,taken_on=excluded.taken_on,status=excluded.status,
            transcript_clean=excluded.transcript_clean''',
                  (video.video_id, video.url, video.page_name, video.views, video.posted_at,
                   video.transcript, taken_on, status, video.transcript_clean))


def start_run(params: dict, path=None) -> int:
    with conn(path) as c:
        cursor = c.execute('INSERT INTO runs (started_at,params_json) VALUES (?,?)',
                           (int(time.time()), json.dumps(params, ensure_ascii=False, default=lambda x: sorted(x))))
        return int(cursor.lastrowid)


def finish_run(run_id: int, log: dict, path=None) -> None:
    with conn(path) as c:
        cursor = c.execute('UPDATE runs SET finished_at=?,log_json=? WHERE id=?',
                           (int(time.time()), json.dumps(log, ensure_ascii=False), run_id))
        if not cursor.rowcount:
            raise ValueError(f'Không tìm thấy lần chạy id={run_id}')
