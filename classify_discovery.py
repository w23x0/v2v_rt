#!/usr/bin/env python3
"""Classify yt-dlp JSONL discovery results using the Phase 1 scope rules."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dedupe import unique_videos


REJECT_TERMS = (
    "no commentary",
    "highlight",
    "highlights",
    "montage",
    "funny moments",
    "best plays",
    "top plays",
    "clip",
    "shorts",
    "guide",
    "tutorial",
    "tips",
    "how to",
    "explained",
    "reaction",
    "vct",
    "esports",
    "official broadcast",
    "caster",
    "playoffs",
    "league",
    "pro match",
    "tournament",
    "champions",
    "major",
)
VOICE_TERMS = ("comms", "team voice", "team comms", "voice comms", "scrim voice")
FORMAT_TERMS = ("full match", "full game", "ranked", "scrim", "premier", "faceit")
# 职业选手/战队/官方频道。Phase 1 目标语料是"普通玩家"开黑，因此这类内容直接拒收。
PRO_TERMS = (
    "nrg", "sentinels", "fnatic", "faze", "100t", "navi", "sen ",
    "esp", "oxygen", "s0m", "sinatraa", "zombs", "asuna", "shahzam",
    "derke", "tenz", "yay", "c9 ", "cloud9", "team flash", "fried",
    "vct", "champions tour", "masters", "official broadcast", "pro vod",
    "pro match", "pro player", "radi", "valorant daily", "professional",
    "esports", "avl", "proguide", "coach", "lets prove",
)


def normalise(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower()).strip()


def classify_video(video: dict[str, Any], game: str) -> dict[str, Any]:
    title = normalise(video.get("title"))
    description = normalise(video.get("description"))
    channel = normalise(video.get("channel") or video.get("uploader"))
    searchable = f"{title} {description} {channel}"
    reasons: list[str] = []
    duration = float(video.get("duration") or 0)

    if video.get("is_live") or video.get("live_status") in {"is_live", "is_upcoming"}:
        reasons.append("live_or_upcoming")
    for term in REJECT_TERMS:
        if term in searchable:
            reasons.append(f"reject_term:{term}")
    for term in PRO_TERMS:
        if term in searchable:
            reasons.append(f"pro_term:{term}")
    if duration and duration < 1200:
        reasons.append("under_20_minutes")

    has_voice_signal = any(term in searchable for term in VOICE_TERMS)
    has_format_signal = any(term in searchable for term in FORMAT_TERMS)
    if not duration:
        reasons.append("missing_duration")

    if reasons:
        decision = "reject" if any(
            reason.startswith("reject_term:")
            or reason.startswith("pro_term:")
            or reason in {"live_or_upcoming", "under_20_minutes"}
            for reason in reasons
        ) else "review"
    elif duration >= 1800 and has_voice_signal:
        decision = "accept"
    elif duration >= 1200 and (has_voice_signal or has_format_signal):
        decision = "review"
    else:
        decision = "review"
        reasons.append("uncertain_voice_or_format")

    return {
        "id": video.get("id"),
        "url": video.get("webpage_url") or video.get("url"),
        "title": video.get("title"),
        "channel": video.get("channel") or video.get("uploader"),
        "duration": video.get("duration"),
        "game": game,
        "decision": decision,
        "reasons": reasons,
        "signals": {"voice": has_voice_signal, "format": has_format_signal},
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--game", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--job-id", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    videos: list[dict[str, Any]] = []
    invalid = 0
    with args.input.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                video = json.loads(line)
            except json.JSONDecodeError:
                invalid += 1
                continue
            if isinstance(video, dict):
                videos.append(video)

    videos, duplicates = unique_videos(videos, args.platform)
    items = [classify_video(video, args.game) for video in videos]

    summary = {
        "total": len(items),
        "accept": sum(item["decision"] == "accept" for item in items),
        "review": sum(item["decision"] == "review" for item in items),
        "reject": sum(item["decision"] == "reject" for item in items),
        "invalid_lines": invalid,
        "duplicates_in_batch": len(duplicates),
    }
    result = {
        "job_id": args.job_id,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "summary": summary,
        "duplicates": duplicates,
        "items": items,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
