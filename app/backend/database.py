"""Small SQLite persistence layer for runner metadata.

Large media files stay in the filesystem. SQLite stores the authoritative
index and JSON payload for jobs, voices, and queue settings.
"""

import json
import sqlite3
from pathlib import Path
from typing import Iterable, Optional

from settings import AI_WORKSPACE


DB_PATH = Path(__import__("os").environ.get(
    "DHJR_DATABASE_PATH", str(AI_WORKSPACE / "app/config/dhjr.sqlite3")
)).expanduser()


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


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


def delete_job(job_id: str) -> None:
    init_db()
    with connect() as conn:
        conn.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))


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
