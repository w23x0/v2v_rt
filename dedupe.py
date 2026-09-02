"""Small, deterministic deduplication helpers for discovery and media stages."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit


def video_key(video: dict[str, Any], platform: str) -> str:
    video_id = str(video.get("id") or "").strip()
    if video_id:
        return f"{platform}:{video_id}"
    raw_url = str(video.get("webpage_url") or video.get("url") or "").strip()
    if not raw_url:
        return ""
    parsed = urlsplit(raw_url)
    canonical_url = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path.rstrip('/')}"
    return f"{platform}:url:{canonical_url}"


def unique_videos(videos: Iterable[dict[str, Any]], platform: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    for video in videos:
        key = video_key(video, platform)
        if key and key in seen:
            duplicates.append({"id": video.get("id"), "key": key, "title": video.get("title")})
            continue
        if key:
            seen.add(key)
        unique.append(video)
    return unique, duplicates


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()
