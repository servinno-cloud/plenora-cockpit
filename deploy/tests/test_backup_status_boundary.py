import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "backup-status-boundary.py"
SPEC = importlib.util.spec_from_file_location("backup_status_boundary", MODULE_PATH)
boundary = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(boundary)


def valid_status():
    return {
        "format_version": 1,
        "last_attempt_at": "2026-08-18T12:00:00Z",
        "last_success_at": "2026-08-18T12:00:00Z",
        "status": "success",
        "backup_id": "2026-08-18T120000Z",
        "database_bytes": 123,
        "media_bytes": 456,
        "checksum_verified": True,
        "git_commit": "unknown",
        "error_code": "",
    }


class BackupStatusBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.root.chmod(0o755)
        self.backup_directory = self.root / "backups"
        self.output_directory = self.root / "run"
        self.backup_directory.mkdir(mode=0o700)
        self.output_directory.mkdir(mode=0o755)
        self.source = self.backup_directory / "status.json"
        self.target = self.output_directory / "backup-status.json"
        boundary.SOURCE = self.source
        boundary.TARGET = self.target

    def tearDown(self):
        self.temporary.cleanup()

    def write_source(self, payload):
        self.source.write_text(payload, encoding="utf-8")
        self.source.chmod(0o600)

    def test_real_production_status_is_atomically_published_with_safe_permissions(self):
        self.write_source(json.dumps(valid_status()))
        boundary.main()

        self.assertEqual(json.loads(self.target.read_text()), valid_status())
        self.assertEqual(stat.S_IMODE(self.source.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.backup_directory.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o644)
        self.assertFalse(list(self.output_directory.glob("*.tmp")))
        if os.geteuid() == 0:
            self.assertEqual((self.target.stat().st_uid, self.target.stat().st_gid), (0, 0))
            readable = subprocess.run(
                [sys.executable, "-c", f"open({str(self.target)!r}, 'rb').read()"],
                check=False,
                preexec_fn=lambda: os.setuid(10003),
            )
            blocked = subprocess.run(
                [sys.executable, "-c", f"open({str(self.source)!r}, 'rb').read()"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                preexec_fn=lambda: os.setuid(10003),
            )
            self.assertEqual(readable.returncode, 0)
            self.assertNotEqual(blocked.returncode, 0)

    def assert_rejected_without_partial_output(self, content):
        self.target.write_text('{"previous":"complete"}\n', encoding="utf-8")
        original = self.target.read_bytes()
        self.write_source(content)
        with self.assertRaises((ValueError, json.JSONDecodeError)):
            boundary.main()
        self.assertEqual(self.target.read_bytes(), original)
        self.assertFalse(list(self.output_directory.glob("*.tmp")))

    def test_malformed_json_is_rejected(self):
        self.assert_rejected_without_partial_output("{")

    def test_unknown_or_privacy_sensitive_fields_are_rejected(self):
        payload = valid_status() | {"recipient_email": "private@example.invalid"}
        self.assert_rejected_without_partial_output(json.dumps(payload))

    def test_missing_required_field_is_rejected(self):
        payload = valid_status()
        del payload["error_code"]
        self.assert_rejected_without_partial_output(json.dumps(payload))

    def test_malformed_types_are_rejected(self):
        malformed = (
            {"format_version": "1"},
            {"database_bytes": True},
            {"media_bytes": -1},
            {"checksum_verified": 1},
            {"last_success_at": "2026-08-18T12:00:00"},
            {"status": "partial"},
            {"git_commit": "branch/main"},
            {"error_code": "contains spaces"},
        )
        for replacement in malformed:
            with self.subTest(replacement=replacement):
                self.assert_rejected_without_partial_output(
                    json.dumps(valid_status() | replacement)
                )

    def test_known_technical_failure_values_are_allowed(self):
        payload = valid_status() | {
            "status": "failed",
            "git_commit": "abcdef1234567890",
            "error_code": "pg_dump_failed",
        }
        self.write_source(json.dumps(payload))
        boundary.main()
        self.assertEqual(json.loads(self.target.read_text()), payload)

    @unittest.skipUnless(hasattr(os, "O_NOFOLLOW"), "O_NOFOLLOW unavailable")
    def test_symlink_source_is_rejected(self):
        real_source = self.backup_directory / "real.json"
        real_source.write_text(json.dumps(valid_status()), encoding="utf-8")
        self.source.symlink_to(real_source)
        with self.assertRaises(OSError):
            boundary.main()
        self.assertFalse(self.target.exists())


if __name__ == "__main__":
    unittest.main()
