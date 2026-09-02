#!/usr/bin/env python3
"""Resumable V2V collection pipeline.

The process supervisor owns persistence. Claude (or another planner) may update
the queue between cycles, but a crashed model session cannot lose pipeline state.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_CONFIG: dict[str, Any] = {
    "state_file": "pipeline_state.json",
    "log_file": "pipeline.log",
    "data_root": ".",
    "poll_seconds": 1800,
    "max_attempts": 3,
    "jobs": [],
    "commands": {
        "discover": [],
        "download": [],
        "clean": [],
        "asr": [],
    },
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temporary.replace(path)


def log(path: Path, message: str) -> None:
    line = f"[{now()}] {message}"
    print(line, flush=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line + "\n")


def render_command(template: list[str], job: dict[str, Any], data_root: Path) -> list[str]:
    values = {
        "job_id": str(job["id"]),
        "query": str(job.get("query", "")),
        "game": str(job.get("game", "unknown")),
        "platform": str(job.get("platform", "unknown")),
        "limit": str(job.get("limit", 20)),
        "data_root": str(data_root),
        "discovery_file": str(data_root / "discovery" / f"{job['id']}.jsonl"),
        "classification_file": str(data_root / "discovery" / f"{job['id']}.classified.json"),
    }
    return [part.format(**values) for part in template]


def stage_status(job: dict[str, Any], stage: str) -> str:
    return str(job.setdefault("stages", {}).get(stage, "pending"))


def run_stage(
    stage: str,
    command: list[str],
    job: dict[str, Any],
    root: Path,
    data_root: Path,
    log_path: Path,
    dry_run: bool,
) -> bool:
    if not command:
        log(log_path, f"job={job['id']} stage={stage} skipped (no command configured)")
        job.setdefault("stages", {})[stage] = "skipped"
        return True

    rendered = render_command(command, job, data_root)
    log(log_path, f"job={job['id']} stage={stage} start: {shlex.join(rendered)}")
    if dry_run:
        job.setdefault("stages", {})[stage] = "dry_run"
        return True

    if stage == "discover":
        (data_root / "discovery").mkdir(parents=True, exist_ok=True)

    try:
        completed = subprocess.run(rendered, cwd=root, check=False)
    except OSError as exc:
        log(log_path, f"job={job['id']} stage={stage} failed to start: {exc}")
        job.setdefault("stages", {})[stage] = "failed"
        return False

    if completed.returncode != 0:
        log(log_path, f"job={job['id']} stage={stage} failed exit={completed.returncode}")
        job.setdefault("stages", {})[stage] = "failed"
        return False

    job.setdefault("stages", {})[stage] = "done"
    log(log_path, f"job={job['id']} stage={stage} done")
    return True


def initialise(config: dict[str, Any], state: dict[str, Any]) -> None:
    existing = {str(job["id"]): job for job in state.get("jobs", [])}
    merged: list[dict[str, Any]] = []
    for source in config.get("jobs", []):
        job = dict(source)
        job_id = str(job.get("id", "")).strip()
        if not job_id:
            raise ValueError("every job needs a non-empty id")
        if job_id in existing:
            job = existing[job_id]
        else:
            job["id"] = job_id
            job["status"] = "pending"
            job["attempts"] = 0
            job["stages"] = {}
            job["created_at"] = now()
        merged.append(job)
    state["jobs"] = merged
    state.setdefault("updated_at", now())


def process_cycle(config: dict[str, Any], state: dict[str, Any], root: Path, data_root: Path, log_path: Path, dry_run: bool) -> bool:
    commands = config.get("commands", {})
    max_attempts = int(config.get("max_attempts", 3))
    changed = False
    for job in state.get("jobs", []):
        if job.get("status") in {"done", "skipped", "awaiting_review"}:
            continue
        if int(job.get("attempts", 0)) >= max_attempts:
            job["status"] = "blocked"
            log(log_path, f"job={job['id']} blocked after {max_attempts} attempts")
            changed = True
            continue

        job["attempts"] = int(job.get("attempts", 0)) + 1
        job["status"] = "running"
        job["last_started_at"] = now()
        changed = True
        failed = False
        for stage in ("discover", "classify", "download", "clean", "asr"):
            if stage_status(job, stage) in {"done", "skipped", "dry_run"}:
                continue
            if not run_stage(stage, list(commands.get(stage, [])), job, root, data_root, log_path, dry_run):
                failed = True
                break
            if stage == "classify" and job.get("approved") is not True:
                job["status"] = "awaiting_review"
                job["review_required_at"] = now()
                log(log_path, f"job={job['id']} awaiting manual review before download")
                state["updated_at"] = now()
                return True

        if failed:
            job["status"] = "pending" if job["attempts"] < max_attempts else "blocked"
            job["last_error_at"] = now()
        else:
            job["status"] = "done"
            job["completed_at"] = now()
        state["updated_at"] = now()
        return True
    return changed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("pipeline_config.json"))
    parser.add_argument("--once", action="store_true", help="run one job cycle and exit")
    parser.add_argument("--interval", type=int, help="override poll interval in seconds")
    parser.add_argument("--dry-run", action="store_true", help="log commands without executing them")
    parser.add_argument("--approve", action="append", default=[], metavar="JOB_ID", help="approve a discovered job for download")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path.cwd()
    config = dict(DEFAULT_CONFIG)
    if args.config.exists():
        loaded = load_json(args.config, {})
        config.update(loaded)
        config["commands"] = {**DEFAULT_CONFIG["commands"], **loaded.get("commands", {})}
    else:
        print(f"config not found: {args.config}; using empty default queue", file=sys.stderr)

    state_path = Path(config.get("state_file", "pipeline_state.json"))
    log_path = Path(config.get("log_file", "pipeline.log"))
    data_root = Path(os.path.expanduser(str(config.get("data_root", "."))))
    state = load_json(state_path, {"version": 1, "jobs": []})
    initialise(config, state)
    approvals = {str(job_id) for job_id in args.approve}
    for job in state.get("jobs", []):
        if str(job.get("id")) in approvals:
            job["approved"] = True
            if job.get("status") == "awaiting_review":
                job["status"] = "pending"
            log(log_path, f"job={job['id']} approved")
    save_json(state_path, state)

    interval = args.interval if args.interval is not None else int(config.get("poll_seconds", 1800))
    while True:
        changed = process_cycle(config, state, root, data_root, log_path, args.dry_run)
        if changed:
            save_json(state_path, state)
        if args.once:
            return 0
        time.sleep(max(1, interval))


if __name__ == "__main__":
    raise SystemExit(main())
