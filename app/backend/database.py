"""Small SQLite persistence layer for runner metadata.

Large media files stay in the filesystem. SQLite stores the authoritative
index and JSON payload for jobs, voices, and queue settings.
"""

import json
import os
import sqlite3
from pathlib import Path
from typing import Iterable, Optional

from job_states import ACTIVE_STATUSES, DONE_STATUSES
DEFAULT_DB_PATH = (
    Path.home()
    / ".local"
    / "share"
    / "digital-human-job-runner"
    / "dhjr.sqlite3"
)
DB_PATH = Path(os.environ.get("DHJR_DATABASE_PATH", str(DEFAULT_DB_PATH))).expanduser()
_STARTUP_REPORTED = False


def is_windows_mounted_path(path: Path) -> bool:
    """Return whether a path lives under WSL's Windows-mounted filesystem."""
    normalized = str(path.expanduser().resolve()).replace("\\", "/")
    return normalized == "/mnt" or normalized.startswith("/mnt/")


def _configure_connection(conn: sqlite3.Connection) -> str:
    """Configure SQLite while keeping a compatibility fallback for /mnt paths."""
    try:
        row = conn.execute("PRAGMA journal_mode=WAL").fetchone()
        journal_mode = str(row[0] if row else "").lower()
    except sqlite3.OperationalError as exc:
        print(f"[WARN] SQLite WAL unavailable: {exc}")
        journal_mode = ""

    if journal_mode != "wal":
        try:
            row = conn.execute("PRAGMA journal_mode=DELETE").fetchone()
            journal_mode = str(row[0] if row else "delete").lower()
            print("[WARN] WAL unavailable on this filesystem; falling back to DELETE mode.")
        except sqlite3.OperationalError:
            raise

    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return journal_mode


def connect() -> sqlite3.Connection:
    global _STARTUP_REPORTED
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    journal_mode = _configure_connection(conn)
    if not _STARTUP_REPORTED:
        print(f"[INFO] SQLite database: {DB_PATH}")
        print(f"[INFO] SQLite journal mode: {journal_mode}")
        if is_windows_mounted_path(DB_PATH):
            print(
                "[WARN] SQLite database is located on a Windows-mounted filesystem. "
                "This may cause WAL disk I/O errors under WSL. "
                "Recommended: use a native Linux path via DHJR_DATABASE_PATH."
            )
        _STARTUP_REPORTED = True
    return conn


def database_health() -> dict:
    """Return a small, read-only health summary for diagnostics and /health."""
    exists_before = DB_PATH.exists()
    try:
        with connect() as conn:
            journal_mode = str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
            integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0]).lower()
        return {
            "path": str(DB_PATH),
            "exists": exists_before or DB_PATH.exists(),
            "writable": os.access(DB_PATH.parent, os.W_OK) and os.access(DB_PATH, os.W_OK),
            "journalMode": journal_mode,
            "integrity": integrity,
        }
    except (OSError, sqlite3.Error) as exc:
        return {
            "path": str(DB_PATH),
            "exists": DB_PATH.exists(),
            "writable": os.access(DB_PATH.parent, os.W_OK) if DB_PATH.parent.exists() else False,
            "journalMode": "unknown",
            "integrity": f"error: {exc}",
        }


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

            CREATE TABLE IF NOT EXISTS voices (
                voice_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                payload TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS queue_state (
                state_key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS gpu_lease (
                lease_id TEXT PRIMARY KEY,
                owner_type TEXT NOT NULL,
                owner_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                acquired_at TEXT NOT NULL
            );
            """
        )


def get_job(job_id: str) -> Optional[dict]:
    init_db()
    with connect() as conn:
        row = conn.execute("SELECT payload FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    return json.loads(row["payload"]) if row else None


def list_jobs() -> list[dict]:
    init_db()
    with connect() as conn:
        rows = conn.execute("SELECT payload FROM jobs ORDER BY created_at DESC").fetchall()
    return [json.loads(row["payload"]) for row in rows]


def upsert_job(job: dict) -> None:
    init_db()
    now = job.get("updated_at") or job.get("finished_at") or job.get("created_at") or ""
    payload = json.dumps(job, ensure_ascii=False, separators=(",", ":"))
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO jobs(job_id, status, created_at, updated_at, payload)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                status = excluded.status,
                updated_at = excluded.updated_at,
                payload = excluded.payload
            """,
            (job["job_id"], job.get("status", "pending"), job.get("created_at", now), now, payload),
        )
        if job.get("status") in DONE_STATUSES:
            conn.execute(
                "DELETE FROM gpu_lease WHERE lease_id = 'gpu' AND owner_type = 'video_generation' "
                "AND owner_id = ? AND (run_id = ? OR ? = '')",
                (job["job_id"], job.get("run_id", ""), job.get("run_id", "")),
            )


def update_job_if_run_matches(
    job: dict,
    expected_run_id: str,
    allowed_statuses: set[str] | frozenset[str] | None = None,
) -> bool:
    """Conditionally persist a run update so a cancelled run cannot revive itself."""
    init_db()
    now = job.get("updated_at") or job.get("finished_at") or job.get("created_at") or ""
    payload = json.dumps(job, ensure_ascii=False, separators=(",", ":"))
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT status, payload FROM jobs WHERE job_id = ?", (job["job_id"],)
        ).fetchone()
        if row is None:
            return False
        current = json.loads(row["payload"])
        if current.get("run_id") != expected_run_id:
            return False
        if allowed_statuses is not None and row["status"] not in allowed_statuses:
            return False
        conn.execute(
            "UPDATE jobs SET status = ?, updated_at = ?, payload = ? WHERE job_id = ?",
            (job.get("status", row["status"]), now, payload, job["job_id"]),
        )
        if job.get("status") in DONE_STATUSES:
            conn.execute(
                "DELETE FROM gpu_lease WHERE lease_id = 'gpu' AND owner_type = 'video_generation' "
                "AND owner_id = ? AND run_id = ?",
                (job["job_id"], expected_run_id),
            )
    return True


def patch_job_if_run_matches(
    job_id: str,
    expected_run_id: str,
    patch: dict,
    allowed_statuses: set[str] | frozenset[str] | None = None,
) -> bool:
    """Merge a small run-scoped patch into the latest payload in one transaction."""
    def merge(target: dict, changes: dict) -> None:
        for key, value in changes.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                merge(target[key], value)
            else:
                target[key] = value

    init_db()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT status, payload FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        if row is None:
            return False
        current = json.loads(row["payload"])
        if current.get("run_id") != expected_run_id:
            return False
        if allowed_statuses is not None and row["status"] not in allowed_statuses:
            return False
        merge(current, patch)
        now = current.get("updated_at") or current.get("finished_at") or current.get("created_at") or ""
        payload = json.dumps(current, ensure_ascii=False, separators=(",", ":"))
        conn.execute(
            "UPDATE jobs SET status = ?, updated_at = ?, payload = ? WHERE job_id = ?",
            (current.get("status", row["status"]), now, payload, job_id),
        )
        if current.get("status") in DONE_STATUSES:
            conn.execute(
                "DELETE FROM gpu_lease WHERE lease_id = 'gpu' AND owner_type = 'video_generation' "
                "AND owner_id = ? AND run_id = ?",
                (job_id, expected_run_id),
            )
    return True


def claim_gpu_lease(owner_type: str, owner_id: str, run_id: str, acquired_at: str) -> dict:
    """Atomically acquire the single local GPU lease."""
    init_db()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM gpu_lease WHERE lease_id = 'gpu'").fetchone()
        if row is not None:
            return {"claimed": False, "owner_type": row["owner_type"], "owner_id": row["owner_id"]}
        conn.execute(
            "INSERT INTO gpu_lease(lease_id, owner_type, owner_id, run_id, acquired_at) VALUES ('gpu', ?, ?, ?, ?)",
            (owner_type, owner_id, run_id, acquired_at),
        )
    return {"claimed": True, "owner_type": owner_type, "owner_id": owner_id}


def release_gpu_lease(owner_type: str, owner_id: str, run_id: str | None = None) -> bool:
    init_db()
    with connect() as conn:
        if run_id is None:
            result = conn.execute(
                "DELETE FROM gpu_lease WHERE lease_id = 'gpu' AND owner_type = ? AND owner_id = ?",
                (owner_type, owner_id),
            )
        else:
            result = conn.execute(
                "DELETE FROM gpu_lease WHERE lease_id = 'gpu' AND owner_type = ? AND owner_id = ? AND run_id = ?",
                (owner_type, owner_id, run_id),
            )
    return result.rowcount > 0


def get_gpu_lease() -> Optional[dict]:
    init_db()
    with connect() as conn:
        row = conn.execute("SELECT * FROM gpu_lease WHERE lease_id = 'gpu'").fetchone()
    return dict(row) if row else None


def claim_job(job_id: str, run_id: str, started_at: str) -> dict:
    """Atomically reserve one job when no other job is active."""
    init_db()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")

        target_row = conn.execute(
            "SELECT payload FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        if target_row is None:
            return {"claimed": False, "reason": "not_found"}

        target = json.loads(target_row["payload"])
        target_status = target.get("status", "pending")
        if target_status in ACTIVE_STATUSES:
            return {
                "claimed": False,
                "reason": "already_active",
                "blocking_job_id": job_id,
            }
        if target_status == "finished":
            return {"claimed": False, "reason": "finished"}

        placeholders = ", ".join("?" for _ in ACTIVE_STATUSES)
        active_rows = conn.execute(
            f"SELECT job_id FROM jobs WHERE status IN ({placeholders}) AND job_id != ? "
            "ORDER BY created_at ASC LIMIT 1",
            (*ACTIVE_STATUSES, job_id),
        ).fetchone()
        if active_rows is not None:
            return {
                "claimed": False,
                "reason": "another_active",
                "blocking_job_id": active_rows["job_id"],
            }

        lease = conn.execute("SELECT * FROM gpu_lease WHERE lease_id = 'gpu'").fetchone()
        if lease is not None:
            return {
                "claimed": False,
                "reason": "gpu_busy",
                "blocking_job_id": lease["owner_id"],
                "blocking_owner_type": lease["owner_type"],
            }

        target["status"] = "starting"
        target["run_id"] = run_id
        target["started_at"] = started_at
        target["finished_at"] = None
        target["error_message"] = None
        target.setdefault("progress", {}).update({
            "stage": "starting",
            "percent": 0,
            "message": "正在启动任务",
        })
        target["updated_at"] = started_at
        payload = json.dumps(target, ensure_ascii=False, separators=(",", ":"))
        conn.execute(
            "UPDATE jobs SET status = ?, updated_at = ?, payload = ? WHERE job_id = ?",
            ("starting", started_at, payload, job_id),
        )
        conn.execute(
            "INSERT INTO gpu_lease(lease_id, owner_type, owner_id, run_id, acquired_at) VALUES ('gpu', 'video_generation', ?, ?, ?)",
            (job_id, run_id, started_at),
        )
        return {"claimed": True, "job": target}


def delete_job(job_id: str) -> None:
    init_db()
    with connect() as conn:
        conn.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
        conn.execute(
            "DELETE FROM gpu_lease WHERE lease_id = 'gpu' AND owner_type = 'video_generation' AND owner_id = ?",
            (job_id,),
        )


def get_voice(voice_id: str) -> Optional[dict]:
    init_db()
    with connect() as conn:
        row = conn.execute("SELECT payload FROM voices WHERE voice_id = ?", (voice_id,)).fetchone()
    return json.loads(row["payload"]) if row else None


def list_voices() -> list[dict]:
    init_db()
    with connect() as conn:
        rows = conn.execute("SELECT payload FROM voices ORDER BY created_at DESC").fetchall()
    return [json.loads(row["payload"]) for row in rows]


def upsert_voice(profile: dict) -> None:
    init_db()
    now = profile.get("updatedAt") or profile.get("createdAt") or ""
    payload = json.dumps(profile, ensure_ascii=False, separators=(",", ":"))
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO voices(voice_id, created_at, updated_at, payload)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(voice_id) DO UPDATE SET
                updated_at = excluded.updated_at,
                payload = excluded.payload
            """,
            (profile["id"], profile.get("createdAt", now), now, payload),
        )


def delete_voice(voice_id: str) -> None:
    init_db()
    with connect() as conn:
        conn.execute("DELETE FROM voices WHERE voice_id = ?", (voice_id,))


def get_queue_state() -> dict:
    init_db()
    with connect() as conn:
        rows = conn.execute("SELECT state_key, value FROM queue_state").fetchall()
    return {row["state_key"]: json.loads(row["value"]) for row in rows}


def set_queue_state(state: dict) -> None:
    init_db()
    with connect() as conn:
        conn.executemany(
            "INSERT INTO queue_state(state_key, value) VALUES (?, ?) "
            "ON CONFLICT(state_key) DO UPDATE SET value = excluded.value",
            [(key, json.dumps(value, ensure_ascii=False)) for key, value in state.items()],
        )


init_db()
