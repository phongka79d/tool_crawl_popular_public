"""Per-channel median viral selection and accent-insensitive script grouping."""
from __future__ import annotations
import re
import statistics
import unicodedata
from dataclasses import dataclass
from backend.core.models import Video
from backend.core.normalize import is_older_than
from backend.services import export_excel


@dataclass
class ViralSelection:
    videos: list[Video]
    recent: int
    median: float | None
    threshold: float | None


def select_channel(videos: list[Video], days: int = 14, min_views: int = 50000,
                   viral_factor: float = 3, max_per_channel: int = 10, now: int | None = None) -> ViralSelection:
    recent = [v for v in videos if v.format in {'video', 'reel'} and not v.is_live
              and (v.posted_at is None or not is_older_than(v.posted_at, days, now))]
    counts = [v.views for v in recent if v.views is not None]
    for video in videos:
        parts = [value for value in (video.reactions, video.comments, video.shares) if value is not None]
        video.interactions = sum(parts) if parts else None
        video.ratio_follow = (video.views / video.page_followers
                              if video.views is not None and video.page_followers else None)
        video.engagement = (video.interactions / video.views
                            if video.interactions is not None and video.views else None)
        video.share_rate = video.shares / video.views if video.shares is not None and video.views else None
        video.ratio_median = None
    if not counts:
        return ViralSelection([], len(recent), None, None)
    median = statistics.median(counts)
    threshold = max(viral_factor * median, min_views)
    for video in recent:
        video.ratio_median = video.views / median if video.views is not None and median else None
    selected = sorted((v for v in recent if v.views is not None and v.views >= threshold),
                      key=lambda v: -(v.views or 0))[:max_per_channel]
    return ViralSelection(selected, len(recent), median, threshold)


def fingerprint(text: str) -> set[str]:
    normalized = unicodedata.normalize('NFD', (text or '').lower().replace('đ', 'd'))
    words = re.findall(r'\w+', ''.join(c for c in normalized if unicodedata.category(c) != 'Mn'))
    return {' '.join(words[index:index + 2]) for index in range(len(words) - 1)}


def similarity(a: set[str], b: set[str]) -> float:
    return len(a & b) / min(len(a), len(b)) if a and b else 0


def dedupe_scripts(videos: list[Video], history: list[dict], threshold: float = 0.5
                   ) -> tuple[list[Video], list[Video], list[str]]:
    groups: list[list[Video]] = []
    prints: list[set[str]] = []
    for video in sorted(videos, key=lambda v: -(v.views or 0)):
        current = fingerprint(video.transcript)
        for group, known in zip(groups, prints):
            if similarity(current, known) >= threshold:
                group.append(video)
                break
        else:
            groups.append([video])
            prints.append(current)
    old = [(entry, fingerprint(entry['transcript'])) for entry in history]
    kept, duplicates, notes = [], [], []
    for group, current in zip(groups, prints):
        first = group[0]
        channels = list(dict.fromkeys(v.page_name for v in group))
        first.so_kenh, first.kenh_cung_dang = len(channels), channels
        for duplicate in group[1:]:
            notes.append(f'Bỏ qua (cùng kịch bản với video {export_excel.format_views(first.views)} view của {first.page_name}): {duplicate.url}')
            duplicates.append(duplicate)
        match = next((entry for entry, known in old if similarity(current, known) >= threshold), None)
        if match:
            date = '/'.join(reversed(match['taken_on'].split('-')))
            notes.append(f"Bỏ qua (kịch bản đã lấy ngày {date} từ {match['page_name']}): {first.url}")
            duplicates.append(first)
        else:
            kept.append(first)
    return kept, duplicates, notes
