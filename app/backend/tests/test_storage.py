import os
import json
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


TEST_ROOT = Path(tempfile.mkdtemp(prefix="dhjr-test-"))
os.environ["DHJR_WORKSPACE"] = str(TEST_ROOT)
os.environ["DHJR_DATABASE_PATH"] = str(TEST_ROOT / "runner.sqlite3")
sys.path.insert(0, str(Path(__file__).parents[1]))

from job_store import create_job, delete_job, list_jobs, load_job, save_job
from database import claim_gpu_lease, claim_job, get_gpu_lease, release_gpu_lease
import database
from path_utils import windows_path_to_wsl
from job_store import build_paths, patch_job
from runner import _build_wsl_command, _to_wsl_path
import runner
import script_assistant
from schemas import JobCreateRequest


class StorageTests(unittest.TestCase):
    def make_request(self):
        return JobCreateRequest(
            title="测试任务",
            subtitle="",
            keywords=["测试"],
            script="这是一条测试文案。",
            background_id="background-test",
            output_type="voice_only",
        )

    def test_job_ids_are_unique_and_persisted(self):
        first = create_job(self.make_request())
        second = create_job(self.make_request())
        self.assertNotEqual(first["job_id"], second["job_id"])
        self.assertEqual(load_job(first["job_id"])["title"], "测试任务")
        self.assertEqual(len(list_jobs()), 2)

        first["status"] = "running"
        save_job(first)
        self.assertEqual(load_job(first["job_id"])["status"], "running")

        delete_job(first["job_id"])
        delete_job(second["job_id"])
        self.assertEqual(len(list_jobs()), 0)

    def test_database_default_is_not_workspace_config(self):
        self.assertNotEqual(
            database.DEFAULT_DB_PATH,
            Path(os.environ["DHJR_WORKSPACE"]) / "app/config/dhjr.sqlite3",
        )

    def test_database_environment_override_is_honored(self):
        self.assertEqual(database.DB_PATH, TEST_ROOT / "runner.sqlite3")

    def test_database_falls_back_when_wal_is_unavailable(self):
        conn = Mock()
        delete_result = Mock()
        delete_result.fetchone.return_value = ("delete",)
        conn.execute.side_effect = [sqlite3.OperationalError("WAL unavailable"), delete_result, None, None, None]

        self.assertEqual(database._configure_connection(conn), "delete")
        self.assertEqual(conn.execute.call_args_list[0].args[0], "PRAGMA journal_mode=WAL")
        self.assertEqual(conn.execute.call_args_list[1].args[0], "PRAGMA journal_mode=DELETE")

    def test_database_init_and_health_are_repeatable(self):
        database.init_db()
        database.init_db()
        health = database.database_health()
        self.assertTrue(health["exists"])
        self.assertTrue(health["writable"])
        self.assertEqual(health["integrity"], "ok")
        self.assertEqual(health["journalMode"], "wal")

    def test_relative_path_conversion_does_not_call_wsl(self):
        converted = _to_wsl_path("scripts/run_cleanvideo_job.sh")
        self.assertTrue(converted.endswith("/scripts/run_cleanvideo_job.sh"))

    def test_windows_asset_path_is_readable_from_wsl(self):
        windows_path = r"C:\Users\rjxxx\assets\background.mp4"
        self.assertEqual(
            windows_path_to_wsl(windows_path),
            "/mnt/c/Users/rjxxx/assets/background.mp4",
        )

    def test_job_claim_allows_only_one_concurrent_runner(self):
        job = create_job(self.make_request())

        def claim(run_number):
            return claim_job(job["job_id"], f"run-{run_number}", "2026-09-04T00:00:00")

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(claim, (1, 2)))

        self.assertEqual(sum(result["claimed"] for result in results), 1)
        self.assertEqual(
            {result["reason"] for result in results if not result["claimed"]},
            {"already_active"},
        )
        delete_job(job["job_id"])

    def test_pipeline_command_uses_job_directories(self):
        command = " ".join(_build_wsl_command("scripts/run_cleanvideo_job.sh", "job-a"))
        self.assertIn("/jobs/job-a/input", command)
        self.assertIn("/jobs/job-a/output", command)
        self.assertIn("/jobs/job-a/work", command)
        self.assertIn("DHJR_PIPELINE_SCRIPTS_DIR=", command)
        self.assertNotIn("DigitalHumanOutput", command)

    def test_local_pipeline_command_passes_engine_workspace(self):
        command = runner._build_local_command("scripts/run_cleanvideo_job.sh", "job-a", "run-a")
        self.assertIn(f"DHJR_ENGINE_WORKSPACE={runner.ENGINE_WORKSPACE}", command)

    def test_clean_video_job_snapshots_background(self):
        background = TEST_ROOT / "assets" / "avatar.mp4"
        background.parent.mkdir(parents=True, exist_ok=True)
        background.write_bytes(b"background-data")
        config = TEST_ROOT / "app" / "config" / "backgrounds.json"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(json.dumps([{
            "id": "background-test",
            "type": "custom",
            "path": str(background),
            "thumbnail_path": str(TEST_ROOT / "thumb.jpg"),
        }]), encoding="utf-8")

        request = self.make_request()
        request.output_type = "clean_video"
        job = create_job(request)
        snapshot = Path(job["paths"]["background_snapshot"])
        self.assertEqual(snapshot.read_bytes(), b"background-data")
        background.unlink()
        self.assertTrue(snapshot.exists())
        delete_job(job["job_id"])

    def test_clean_video_job_snapshots_selected_outro(self):
        background = TEST_ROOT / "assets" / "avatar.mp4"
        outro = TEST_ROOT / "assets" / "outro.mp4"
        background.parent.mkdir(parents=True, exist_ok=True)
        background.write_bytes(b"background-data")
        outro.write_bytes(b"outro-data")
        config = TEST_ROOT / "app" / "config" / "backgrounds.json"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(json.dumps([{
            "id": "background-test",
            "type": "custom",
            "path": str(background),
            "thumbnail_path": str(TEST_ROOT / "thumb.jpg"),
        }]), encoding="utf-8")

        request = self.make_request()
        request.output_type = "clean_video"
        request.outro_id = "outro-test"
        job = create_job(request, outro_data={"name": "测试片尾", "path": str(outro)})
        snapshot = Path(job["paths"]["outro_snapshot"])
        self.assertEqual(snapshot.read_bytes(), b"outro-data")
        self.assertEqual(job["outro_name"], "测试片尾")
        delete_job(job["job_id"])

    def test_cancelled_run_rejects_stale_runner_write(self):
        job = create_job(self.make_request())
        claimed = claim_job(job["job_id"], "run-cancel-race", "2026-09-04T00:00:00")
        stale = claimed["job"]

        cancelled = load_job(job["job_id"])
        cancelled["status"] = "cancelled"
        save_job(cancelled)

        stale["status"] = "running"
        self.assertFalse(save_job(
            stale,
            expected_run_id="run-cancel-race",
            allowed_statuses={"starting"},
        ))
        self.assertEqual(load_job(job["job_id"])["status"], "cancelled")
        delete_job(job["job_id"])

    def test_popen_failure_does_not_leave_starting_job(self):
        job = create_job(self.make_request())
        script = TEST_ROOT / "run_voice_only_job.sh"
        script.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")

        with patch.object(runner, "RUN_VOICE_SCRIPT", str(script)), patch.object(
            runner.subprocess, "Popen", side_effect=OSError("wsl.exe missing")
        ):
            with self.assertRaises(RuntimeError):
                runner.start_job(job["job_id"])

        self.assertEqual(load_job(job["job_id"])["status"], "failed")
        delete_job(job["job_id"])

    def test_prepare_only_accepts_starting_status(self):
        job = create_job(self.make_request())
        from prepare_job import validate_job
        with self.assertRaises(ValueError):
            validate_job(job, job["job_id"])
        delete_job(job["job_id"])

    def test_canonical_paths_keep_run_metadata(self):
        paths = build_paths("job-paths", "clean_video")
        self.assertTrue(paths["run_metadata"].endswith("run.json"))
        self.assertEqual(paths["background_snapshot"].replace("\\", "/").split("/")[-1], "avatar.mp4")

    def test_gpu_lease_is_shared_by_voice_and_video(self):
        self.assertTrue(claim_gpu_lease("voice_training", "voice-a", "voice-run", "2026-09-04T00:00:00")["claimed"])
        job = create_job(self.make_request())
        claimed = claim_job(job["job_id"], "video-run", "2026-09-04T00:00:01")
        self.assertFalse(claimed["claimed"])
        self.assertEqual(claimed["reason"], "gpu_busy")
        self.assertEqual(get_gpu_lease()["owner_type"], "voice_training")
        release_gpu_lease("voice_training", "voice-a", "voice-run")
        delete_job(job["job_id"])

    def test_run_patch_preserves_fields_from_other_writer(self):
        job = create_job(self.make_request())
        claimed = claim_job(job["job_id"], "run-patch", "2026-09-04T00:00:00")
        self.assertTrue(patch_job(job["job_id"], "run-patch", {"launcher_pid": 1234}, {"starting"}))
        self.assertTrue(patch_job(job["job_id"], "run-patch", {"progress": {"percent": 8}}, {"starting"}))
        current = load_job(job["job_id"])
        self.assertEqual(current["launcher_pid"], 1234)
        self.assertEqual(current["progress"]["percent"], 8)
        delete_job(job["job_id"])

    @unittest.skipUnless(os.name == "nt", "native Windows install test")
    def test_native_windows_ollama_runner_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            install_dir = Path(tmp) / "Ollama"
            ollama_bin = install_dir / "ollama.exe"
            runner_bin = install_dir / "lib" / "ollama" / "llama-server.exe"
            runner_bin.parent.mkdir(parents=True)
            ollama_bin.write_bytes(b"ollama")
            runner_bin.write_bytes(b"runner")

            with patch.object(script_assistant, "_find_ollama_bin", return_value=str(ollama_bin)):
                self.assertEqual(Path(script_assistant._find_runner_bin()), runner_bin.resolve())


if __name__ == "__main__":
    unittest.main()
