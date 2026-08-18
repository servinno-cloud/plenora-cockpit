import json
from datetime import UTC, datetime, timedelta

from src.probes import backup_probe, host_probe


def test_backup_probe_reads_only_allowlisted_status(tmp_path):
    path = tmp_path / "status.json"
    now = datetime.now(UTC)
    path.write_text(
        json.dumps(
            {
                "format_version": 1,
                "last_attempt_at": now.isoformat(),
                "last_success_at": (now - timedelta(hours=27)).isoformat(),
                "status": "success",
                "backup_id": "safe-id",
                "database_bytes": 1024,
                "media_bytes": 2048,
                "checksum_verified": True,
                "git_commit": "unknown",
                "error_code": "",
            }
        )
    )
    observations = backup_probe(str(path), now=now)
    assert {item["signal"] for item in observations} >= {
        "backup.status",
        "backup.success_age_seconds",
    }
    assert next(
        item["value"] for item in observations if item["signal"] == "backup.git_commit"
    ) == "unknown"
    assert not any("path" in str(item) or "email" in str(item) for item in observations)


def test_backup_probe_fails_closed_and_host_is_read_only(tmp_path):
    bad = tmp_path / "status.json"
    bad.write_text('{"last_success_at":"x","secret":"no"}')
    assert backup_probe(str(bad))[0]["state"] == "UNKNOWN"
    signals = {item["signal"] for item in host_probe(str(tmp_path))}
    assert "host.uptime_seconds" in signals and "disk.root.used_percent" in signals
