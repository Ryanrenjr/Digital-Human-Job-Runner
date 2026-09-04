#!/usr/bin/env python3
"""Read one authoritative job value for shell scripts without parsing job.json."""

import json
import sys

from job_store import load_job


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: python job_state_get.py JOB_ID FIELD", file=sys.stderr)
        return 2
    job = load_job(sys.argv[1])
    if job is None:
        print("", end="")
        return 1
    value = job
    for part in sys.argv[2].split("."):
        if not isinstance(value, dict):
            value = None
            break
        value = value.get(part)
    if isinstance(value, bool):
        print("yes" if value else "no")
    elif value is None:
        print("")
    elif isinstance(value, (dict, list)):
        print(json.dumps(value, ensure_ascii=False))
    else:
        print(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
