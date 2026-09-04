import os
import sys
import tempfile
import unittest
from pathlib import Path


TEST_ROOT = Path(tempfile.mkdtemp(prefix="dhjr-test-"))
os.environ["DHJR_WORKSPACE"] = str(TEST_ROOT)
os.environ["DHJR_DATABASE_PATH"] = str(TEST_ROOT / "runner.sqlite3")
sys.path.insert(0, str(Path(__file__).parents[1]))

from job_store import create_job, delete_job, list_jobs, load_job, save_job
from runner import _build_wsl_command
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
        self.assertEqual(len(list_jobs()), 1)

    def test_pipeline_command_uses_job_directories(self):
        command = " ".join(_build_wsl_command("scripts/run_cleanvideo_job.sh", "job-a"))
        self.assertIn("/jobs/job-a/input", command)
        self.assertIn("/jobs/job-a/output", command)
        self.assertIn("/jobs/job-a/work", command)
        self.assertIn("DHJR_PIPELINE_SCRIPTS_DIR=", command)
        self.assertNotIn("DigitalHumanOutput", command)


if __name__ == "__main__":
    unittest.main()
