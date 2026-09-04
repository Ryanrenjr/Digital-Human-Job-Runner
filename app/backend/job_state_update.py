#!/usr/bin/env python3
"""Update a job state from a shell pipeline without bypassing SQLite."""

import os
import sys

from job_states import ACTIVE_STATUSES
from job_store import load_job, patch_job, save_job


def main() -> None:
    if len(sys.argv) < 4:
        raise SystemExit("Usage: job_state_update.py JOB_ID STATUS MESSAGE")
    job_id, status, message = sys.argv[1:4]
    job = load_job(job_id)
    if not job:
        return
    job["status"] = status
    if status in {"failed", "finished", "cancelled"} and not job.get("finished_at"):
        from datetime import datetime
        job["finished_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    if status == "failed":
        job["error_message"] = message
    progress = job.setdefault("progress", {})
    progress["stage"] = status
    progress["percent"] = 100 if status == "finished" else progress.get("percent", 0)
    progress["message"] = message
    run_id = os.getenv("DHJR_RUN_ID", "").strip()
    if run_id:
        allowed = ACTIVE_STATUSES - {"cancelling"} if status in {"failed", "finished", "cancelled"} else ACTIVE_STATUSES
        patch_job(
            job_id,
            run_id,
            {key: value for key, value in job.items() if key in {"status", "finished_at", "error_message", "progress"}},
            allowed,
        )
    else:
        save_job(job)


if __name__ == "__main__":
    main()
