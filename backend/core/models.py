"""Shared records for scanning, local transcription and content history."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Page:
    url: str
    name: str = ""
    followers: int | None = None


@dataclass
class Video:
    video_id: str
    url: str
    page_url: str
    page_name: str = ""
    page_followers: int | None = None
    posted_at: int | None = None
    format: str = "video"
    is_live: bool = False
    duration_s: float | None = None
    views: int | None = None
    reactions: int | None = None
    comments: int | None = None
    shares: int | None = None
    interactions: int | None = None
    ratio_follow: float | None = None
    ratio_median: float | None = None
    engagement: float | None = None
    share_rate: float | None = None
    caption: str = ""
    transcript: str = ""
    transcript_clean: str = ""
    transcript_status: str = ""
    transcript_language: str = ""
    so_kenh: int = 1
    kenh_cung_dang: list[str] = field(default_factory=list)
    taken_on: str = ""
    notes: list[str] = field(default_factory=list)


VIDEO_KINDS = frozenset({"video", "reel"})
KIND_LABELS = {"video": "Video", "reel": "Reel"}
