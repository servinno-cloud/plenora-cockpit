import importlib.util
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).parents[1] / "offsite-status-boundary.py"
SPEC = importlib.util.spec_from_file_location("offsite_status_boundary", MODULE_PATH)
boundary = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(boundary)


def valid_status():
    return {
        "format_version": 1,
        "attempted_at": "2026-09-14T02:23:25Z",
        "last_success_at": "2026-09-14T02:23:25Z",
        "status": "success",
        "backup_id": "2026-09-14T022025Z",
        "last_success_backup_id": "2026-09-14T022025Z",
        "source_git_commit": "a" * 40,
        "local_verified": True,
        "encrypted_bytes": 655802,
        "ciphertext_sha256": "b" * 64,
        "age_key_version": "age-2026-02",
        "remote_provider": "backblaze-b2-eu-central",
        "remote_bucket_identifier": "production-bucket-alias",
        "remote_object_prefix": "production/2026-09-14T022025Z/",
        "retain_until": "2026-09-28T02:20:25Z",
        "object_lock_verified": True,
        "error_code": "",
    }


SYSTEMD = {
    "uploader_service_ok": True,
    "finalizer_service_ok": True,
    "uploader_timer_enabled": True,
    "uploader_timer_active": True,
    "finalizer_timer_enabled": True,
    "finalizer_timer_active": True,
}


class OffsiteStatusBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.root = self.enterContext(tempfile.TemporaryDirectory())
        directory = Path(self.root)
        self.source = directory / "status.json"
        self.target = directory / "offsite-status.json"
        boundary.SOURCE = self.source
        boundary.TARGET = self.target

    @patch.object(boundary, "systemd_status", return_value=SYSTEMD)
    def test_safe_status_is_reduced_and_published_atomically(self, _systemd):
        self.source.write_text(json.dumps(valid_status()), encoding="utf-8")
        boundary.main()
        result = json.loads(self.target.read_text(encoding="utf-8"))
        self.assertTrue(result["available"])
        self.assertEqual(result["attempted_at"], "2026-09-14T02:23:25Z")
        self.assertEqual(result["backup_id"], "2026-09-14T022025Z")
        self.assertEqual(result["last_success_backup_id"], "2026-09-14T022025Z")
        self.assertNotIn("ciphertext_sha256", result)
        self.assertNotIn("remote_bucket_identifier", result)
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o644)

    @patch.object(boundary, "systemd_status", return_value=SYSTEMD)
    def test_missing_or_sensitive_status_fails_closed(self, _systemd):
        boundary.main()
        missing = json.loads(self.target.read_text(encoding="utf-8"))
        self.assertFalse(missing["available"])
        self.assertEqual(missing["backup_id"], "")
        self.assertEqual(missing["error_code"], "status_unavailable")

        self.source.write_text(
            json.dumps(valid_status() | {"application_key": "must-not-cross-boundary"}),
            encoding="utf-8",
        )
        boundary.main()
        rejected = json.loads(self.target.read_text(encoding="utf-8"))
        self.assertFalse(rejected["available"])
        self.assertNotIn("application_key", self.target.read_text(encoding="utf-8"))

    def test_oneshot_inactive_after_success_is_healthy(self):
        class Completed:
            def __init__(self, output, returncode=0):
                self.stdout = output
                self.returncode = returncode

        def run(command, **_kwargs):
            if command[1] == "show" and command[2].endswith(".service"):
                return Completed("Result=success\nExecMainStatus=0\nActiveState=inactive\n")
            if command[1] == "show":
                return Completed("ActiveState=active\n")
            return Completed("enabled\n")

        with patch.object(boundary.subprocess, "run", side_effect=run):
            result = boundary.systemd_status()
        self.assertTrue(result["uploader_service_ok"])
        self.assertTrue(result["finalizer_service_ok"])
        self.assertTrue(result["uploader_timer_active"])


if __name__ == "__main__":
    unittest.main()
