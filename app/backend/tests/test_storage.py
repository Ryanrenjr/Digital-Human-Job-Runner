import os
import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


TEST_ROOT = Path(tempfile.mkdtemp(prefix="dhjr-test-"))
os.environ["DHJR_WORKSPACE"] = str(TEST_ROOT)
os.environ["DHJR_DATABASE_PATH"] = str(TEST_ROOT / "runner.sqlite3")
sys.path.insert(0, str(Path(__file__).parents[1]))

from job_store import create_job, delete_job, list_jobs, load_job, save_job
from database import claim_job
from runner import _build_wsl_command, _to_wsl_path
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

    def test_relative_path_conversion_does_not_call_wsl(self):
        converted = _to_wsl_path("scripts/run_cleanvideo_job.sh")
        self.assertTrue(converted.endswith("/scripts/run_cleanvideo_job.sh"))

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


if __name__ == "__main__":
    unittest.main()
