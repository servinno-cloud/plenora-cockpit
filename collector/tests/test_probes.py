import json
from datetime import UTC, datetime, timedelta

import pytest

from src.probes import backup_probe, host_probe, offsite_backup_probe


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


def offsite_status(now):
    return {
        "format_version": 1,
        "available": True,
        "attempted_at": now.isoformat().replace("+00:00", "Z"),
        "last_success_at": now.isoformat().replace("+00:00", "Z"),
        "status": "success",
        "last_success_backup_id": "2026-09-14T022025Z",
        "age_key_version": "age-2026-02",
        "local_verified": True,
        "object_lock_verified": True,
        "error_code": "",
        "uploader_service_ok": True,
        "finalizer_service_ok": True,
        "uploader_timer_enabled": True,
        "uploader_timer_active": True,
        "finalizer_timer_enabled": True,
        "finalizer_timer_active": True,
    }


def offsite_state(path, now, **changes):
    value = offsite_status(now) | changes
    path.write_text(json.dumps(value), encoding="utf-8")
    return next(item for item in offsite_backup_probe(str(path), now=now)
                if item["signal"] == "offsite.health")["state"]


@pytest.mark.parametrize(
    ("age", "expected"),
    ((timedelta(hours=26), "HEALTHY"),
     (timedelta(hours=27), "WARNING"),
     (timedelta(hours=49), "CRITICAL")),
)
def test_offsite_backup_age_thresholds(tmp_path, age, expected):
    now = datetime.now(UTC)
    assert offsite_state(
        tmp_path / "offsite.json", now,
        last_success_at=(now - age).isoformat().replace("+00:00", "Z"),
    ) == expected


@pytest.mark.parametrize(
    "changes",
    (
        {"status": "failed", "error_code": "provider_failed"},
        {"object_lock_verified": False},
        {"status": "partial", "finalizer_service_ok": False},
        {"uploader_timer_enabled": False},
        {"finalizer_timer_active": False},
    ),
)
def test_offsite_backup_hard_failures_are_critical(tmp_path, changes):
    now = datetime.now(UTC)
    assert offsite_state(tmp_path / "offsite.json", now, **changes) == "CRITICAL"


@pytest.mark.parametrize("minutes", (10, 44))
def test_offsite_pending_provider_verification_uses_grace_period(tmp_path, minutes):
    now = datetime.now(UTC)
    assert offsite_state(
        tmp_path / "offsite.json",
        now,
        attempted_at=(now - timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z"),
        status="partial",
        object_lock_verified=None,
        error_code="awaiting_provider_verification",
    ) == "HEALTHY"


@pytest.mark.parametrize(
    "changes",
    (
        {"status": "partial", "error_code": "awaiting_provider_verification",
         "object_lock_verified": None, "pending_minutes": 46},
        {"status": "partial", "error_code": "provider_failed",
         "object_lock_verified": None, "pending_minutes": 10},
        {"status": "partial", "error_code": "awaiting_provider_verification",
         "object_lock_verified": None, "local_verified": False, "pending_minutes": 10},
        {"status": "partial", "error_code": "awaiting_provider_verification",
         "object_lock_verified": None, "finalizer_service_ok": False, "pending_minutes": 10},
        {"status": "partial", "error_code": "awaiting_provider_verification",
         "object_lock_verified": None, "finalizer_timer_enabled": False, "pending_minutes": 10},
        {"status": "failed", "error_code": "source_commit_unknown", "pending_minutes": 10},
    ),
)
def test_offsite_pending_failures_remain_critical(tmp_path, changes):
    now = datetime.now(UTC)
    values = changes.copy()
    minutes = values.pop("pending_minutes")
    values["attempted_at"] = (
        now - timedelta(minutes=minutes)
    ).isoformat().replace("+00:00", "Z")
    assert offsite_state(tmp_path / "offsite.json", now, **values) == "CRITICAL"


def test_offsite_oneshot_services_may_be_inactive_after_success(tmp_path):
    now = datetime.now(UTC)
    assert offsite_state(tmp_path / "offsite.json", now) == "HEALTHY"


def test_missing_offsite_status_fails_closed_without_exposing_details(tmp_path):
    observations = offsite_backup_probe(str(tmp_path / "missing.json"))
    assert observations[0]["signal"] == "offsite.health"
    assert observations[0]["state"] == "CRITICAL"
    assert observations[1]["value"] == "status_unavailable"
