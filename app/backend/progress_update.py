#!/usr/bin/env python3
"""Write a live pipeline progress update for one job."""

import json
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) < 5:
        raise SystemExit(
            "Usage: progress_update.py JOB_ID STAGE PERCENT MESSAGE [CURRENT] [TOTAL]"
        )

    job_id, stage = sys.argv[1:3]
    percent = max(0, min(100, int(float(sys.argv[3]))))
    message = sys.argv[4]
    current = int(sys.argv[5]) if len(sys.argv) > 5 else None
    total = int(sys.argv[6]) if len(sys.argv) > 6 else None

    workspace = Path(__import__("os").environ.get("DHJR_WORKSPACE", Path.cwd()))
    job_path = workspace / "jobs" / job_id / "job.json"
    if not job_path.exists():
        return

    job = json.loads(job_path.read_text(encoding="utf-8"))
    progress = job.setdefault("progress", {})
    progress.update({"stage": stage, "percent": percent, "message": message})
    if current is not None:
        progress["current_window"] = current
    if total is not None:
        progress["total_windows"] = total

    # Replace atomically so the API never reads half-written JSON.
    temp_path = job_path.with_suffix(".progress.tmp")
    temp_path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(job_path)


if __name__ == "__main__":
    main()
