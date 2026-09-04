#!/usr/bin/env python3
"""Write a live pipeline progress update for one job."""

import os
import sys

from job_states import ACTIVE_STATUSES
from job_store import load_job, save_job


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

    job = load_job(job_id)
    if not job:
        return

    progress = job.setdefault("progress", {})
    progress.update({"stage": stage, "percent": percent, "message": message})
    if current is not None:
        progress["current_window"] = current
    if total is not None:
        progress["total_windows"] = total

    run_id = os.getenv("DHJR_RUN_ID", "").strip()
    if run_id:
        save_job(job, expected_run_id=run_id, allowed_statuses=ACTIVE_STATUSES)
    else:
        save_job(job)


if __name__ == "__main__":
    main()
