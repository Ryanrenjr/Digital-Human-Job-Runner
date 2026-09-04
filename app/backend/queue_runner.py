import asyncio
import json
import logging
import os
import signal
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from database import get_queue_state, set_queue_state
from database import release_gpu_lease
from job_states import ACTIVE_STATUSES, DONE_STATUSES
from job_store import list_jobs, patch_job, save_job
from runner import JobStartConflict, is_job_process_running, start_job
from settings import AI_WORKSPACE, SHUTDOWN_EXE
from voice_store import list_voice_profiles, load_voice_profile, save_voice_profile
from voice_training_runner import is_voice_training_process_running, recover_stale_voice_training

logger = logging.getLogger(__name__)

STATE_PATH   = AI_WORKSPACE / "app/config/queue_state.json"

_DONE = DONE_STATUSES


class QueueRunner:
    def __init__(self):
        self._state = self._load_state()
        self._task: Optional[asyncio.Task] = None
        self._missing_process_counts: dict[str, int] = {}
        self._missing_voice_counts: dict[str, int] = {}

    # ── persistence ────────────────────────────────────────────────────────

    def _load_state(self) -> dict:
        stored = get_queue_state()
        if stored:
            return {
                "auto_run": False,
                "paused": False,
                "shutdown_after_complete": False,
                **stored,
            }
        if STATE_PATH.exists():
            try:
                return json.loads(STATE_PATH.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("[QueueRunner] State load failed: %s", exc)
        return {"auto_run": False, "paused": False, "shutdown_after_complete": False}

    def _save_state(self) -> None:
        set_queue_state(self._state)
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temp_path = STATE_PATH.with_suffix(".json.tmp")
        temp_path.write_text(
            json.dumps(self._state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        temp_path.replace(STATE_PATH)

    # ── startup recovery ───────────────────────────────────────────────────

    def recover_stale_jobs(self) -> None:
        """On startup, any job stuck in status=running with no live process → failed."""
        for job in list_jobs():
            if job.get("status") not in ACTIVE_STATUSES:
                continue
            job_id = job["job_id"]
            if not is_job_process_running(job_id):
                logger.warning("[QueueRunner] Stale job %s → failed", job_id)
                run_id = job.get("run_id")
                if run_id:
                    patch_job(
                        job_id, run_id,
                        {
                            "status": "cancelled" if job.get("status") == "cancelling" else "failed",
                            "finished_at": datetime.now().isoformat(timespec="seconds"),
                            "error_message": "取消任务已完成" if job.get("status") == "cancelling" else "进程未找到，已恢复为失败状态",
                            "progress": {"stage": "cancelled" if job.get("status") == "cancelling" else "failed", "message": "启动时恢复"},
                            "launcher_pid": None,
                            "process_group_id": None,
                        },
                        ACTIVE_STATUSES,
                    )
                else:
                    job["status"] = "failed"
                    job["error_message"] = "Process not found on startup — recovered as failed"
                    job.setdefault("progress", {})
                    job["progress"]["stage"] = "failed"
                    job["progress"]["message"] = "Recovered on startup"
                    save_job(job)
        recover_stale_voice_training()

    def watchdog(self) -> None:
        """Recover unexpectedly dead GPU processes without waiting for a restart."""
        for job in list_jobs():
            status = job.get("status")
            job_id = job.get("job_id")
            run_id = job.get("run_id")
            if status not in ACTIVE_STATUSES or not job_id or not run_id:
                continue
            if status == "cancelling":
                if not is_job_process_running(job_id):
                    patch_job(
                        job_id, run_id,
                        {
                            "status": "cancelled",
                            "finished_at": datetime.now().isoformat(timespec="seconds"),
                            "error_message": "Cancelled by user.",
                            "progress": {"stage": "cancelled", "message": "Cancelled by user."},
                            "launcher_pid": None,
                            "process_group_id": None,
                        },
                        {"cancelling"},
                    )
                continue
            if is_job_process_running(job_id):
                self._missing_process_counts.pop(job_id, None)
                continue
            missing = self._missing_process_counts.get(job_id, 0) + 1
            self._missing_process_counts[job_id] = missing
            if missing < 3:
                continue
            patch_job(
                job_id, run_id,
                {
                    "status": "failed",
                    "finished_at": datetime.now().isoformat(timespec="seconds"),
                    "error_message": "任务进程意外退出，已由后台监控恢复。",
                    "progress": {"stage": "failed", "message": "任务进程意外退出，已由后台监控恢复。"},
                    "launcher_pid": None,
                    "process_group_id": None,
                },
                ACTIVE_STATUSES,
            )
            self._missing_process_counts.pop(job_id, None)

        for profile in list_voice_profiles():
            voice_id = profile.get("id")
            if profile.get("trainingStatus") != "training" or not voice_id:
                continue
            if is_voice_training_process_running(voice_id):
                self._missing_voice_counts.pop(voice_id, None)
                continue
            missing = self._missing_voice_counts.get(voice_id, 0) + 1
            self._missing_voice_counts[voice_id] = missing
            if missing >= 3:
                current = load_voice_profile(voice_id)
                if current and current.get("trainingStatus") == "training":
                    current["trainingStatus"] = "failed"
                    current["trainingFinishedAt"] = datetime.now().isoformat(timespec="seconds")
                    current["trainingError"] = "训练进程意外退出，已由后台监控恢复。"
                    current["trainingPid"] = None
                    current["trainingProcessGroupId"] = None
                    save_voice_profile(current)
                    release_gpu_lease("voice_training", voice_id, current.get("trainingRunId"))
                self._missing_voice_counts.pop(voice_id, None)

    # ── properties ─────────────────────────────────────────────────────────

    @property
    def auto_run(self) -> bool:
        return bool(self._state.get("auto_run", False))

    @property
    def paused(self) -> bool:
        return bool(self._state.get("paused", False))

    @property
    def shutdown_after_complete(self) -> bool:
        return bool(self._state.get("shutdown_after_complete", False))

    # ── controls ───────────────────────────────────────────────────────────

    def set_auto_run(self, enabled: bool) -> None:
        self._state["auto_run"] = enabled
        self._save_state()
        logger.info("[QueueRunner] auto_run → %s", enabled)

    def set_paused(self, paused: bool) -> None:
        self._state["paused"] = paused
        self._save_state()
        logger.info("[QueueRunner] paused → %s", paused)

    def set_shutdown_after_complete(self, enabled: bool) -> None:
        self._state["shutdown_after_complete"] = enabled
        self._save_state()
        logger.info("[QueueRunner] shutdown_after_complete → %s", enabled)

    @property
    def worker_alive(self) -> bool:
        return self._task is not None and not self._task.done()

    # ── status ─────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        try:
            all_jobs = list_jobs()
        except Exception as exc:
            logger.warning("[QueueRunner] get_status list_jobs error: %s", exc)
            all_jobs = []

        counts: dict = {}
        for j in all_jobs:
            s = j.get("status", "unknown")
            counts[s] = counts.get(s, 0) + 1

        running_job = next((j for j in all_jobs if j.get("status") in ACTIVE_STATUSES), None)
        n_pending   = counts.get("pending", 0)
        n_running   = sum(counts.get(state, 0) for state in ACTIVE_STATUSES)

        if n_running > 0:
            status = "paused" if self.paused else "running"
        elif n_pending > 0:
            status = "paused" if self.paused else "idle"
        elif all_jobs and all(j.get("status") in _DONE for j in all_jobs):
            status = "completed"
        else:
            status = "idle"

        return {
            "auto_run":                self.auto_run,
            "paused":                  self.paused,
            "status":                  status,
            "current_job_id":          running_job["job_id"]    if running_job else None,
            "current_job_title":       running_job.get("title") if running_job else None,
            "pending_count":           n_pending,
            "running_count":           n_running,
            "finished_count":          counts.get("finished",  0),
            "failed_count":            counts.get("failed",    0),
            "cancelled_count":         counts.get("cancelled", 0),
            "shutdown_after_complete": self.shutdown_after_complete,
            "worker_alive":            self.worker_alive,
        }

    # ── queue operations ───────────────────────────────────────────────────

    def run_next_pending(self) -> Optional[str]:
        """Immediately start the next pending job. Returns job_id or None."""
        all_jobs = list_jobs()
        pending = sorted(
            (j for j in all_jobs if j.get("status") == "pending"),
            key=lambda j: j.get("created_at", ""),
        )
        if not pending:
            return None
        job_id = pending[0]["job_id"]
        try:
            pid = start_job(job_id)
        except JobStartConflict:
            return None
        logger.info("[QueueRunner] run_next_pending → %s (PID %d)", job_id, pid)
        return job_id

    def tick(self) -> None:
        """Periodic tick: auto-start next pending job when conditions allow."""
        if not self.auto_run or self.paused:
            return

        all_jobs = list_jobs()
        if any(j.get("status") in ACTIVE_STATUSES for j in all_jobs):
            return

        pending = sorted(
            (j for j in all_jobs if j.get("status") == "pending"),
            key=lambda j: j.get("created_at", ""),
        )

        if not pending:
            if (
                self.shutdown_after_complete
                and all_jobs
                and all(j.get("status") in _DONE for j in all_jobs)
            ):
                logger.info("[QueueRunner] All jobs done — initiating Windows shutdown")
                # Disable immediately so it never fires again (this cycle or after reboot)
                self.set_shutdown_after_complete(False)
                subprocess.Popen(
                    [SHUTDOWN_EXE, "/s", "/t", "30"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            return

        job_id = pending[0]["job_id"]
        try:
            pid = start_job(job_id)
            logger.info("[QueueRunner] Auto-started %s (PID %d)", job_id, pid)
        except Exception as exc:
            logger.warning("[QueueRunner] Could not auto-start %s: %s", job_id, exc)

    # ── asyncio worker ─────────────────────────────────────────────────────

    async def _worker(self) -> None:
        await asyncio.sleep(8)
        while True:
            await asyncio.sleep(5)
            try:
                self.watchdog()
                self.tick()
            except Exception as exc:
                logger.warning("[QueueRunner] Tick error: %s", exc)

    def start_worker(self) -> None:
        self._task = asyncio.create_task(self._worker())
        logger.info(
            "[QueueRunner] Worker started (auto_run=%s, paused=%s)",
            self.auto_run, self.paused,
        )

    def stop_worker(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None


queue_runner = QueueRunner()
