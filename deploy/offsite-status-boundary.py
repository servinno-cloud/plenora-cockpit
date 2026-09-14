#!/usr/bin/env python3
import json
import os
import re
import stat
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

SOURCE = Path("/var/lib/plenora-offsite/status.json")
TARGET = Path("/run/plenora-cockpit/offsite-status.json")
MAX_SOURCE_BYTES = 16 * 1024
EXPECTED_FIELDS = {
    "format_version", "attempted_at", "last_success_at", "status", "backup_id",
    "last_success_backup_id", "source_git_commit", "local_verified", "encrypted_bytes",
    "ciphertext_sha256", "age_key_version", "remote_provider", "remote_bucket_identifier",
    "remote_object_prefix", "retain_until", "object_lock_verified", "error_code",
}
SERVICES = {
    "uploader": "plenora-offsite-backup.service",
    "finalizer": "plenora-offsite-finalizer.service",
}
TIMERS = {
    "uploader": "plenora-offsite-backup.timer",
    "finalizer": "plenora-offsite-finalizer.timer",
}


def _utc_timestamp(value: object, *, allow_empty: bool = False) -> str:
    if allow_empty and value == "":
        return ""
    if not isinstance(value, str):
        raise ValueError("Offsite timestamp is invalid")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() != timedelta(0):
        raise ValueError("Offsite timestamp must use UTC")
    return value


def validate(payload: object) -> dict:
    if not isinstance(payload, dict) or set(payload) != EXPECTED_FIELDS:
        raise ValueError("Offsite status fields are invalid")
    if type(payload["format_version"]) is not int or payload["format_version"] != 1:
        raise ValueError("Offsite format version is invalid")
    _utc_timestamp(payload["attempted_at"])
    _utc_timestamp(payload["last_success_at"], allow_empty=True)
    _utc_timestamp(payload["retain_until"], allow_empty=True)
    if payload["status"] not in {"never", "running", "success", "partial", "failed"}:
        raise ValueError("Offsite status is invalid")
    for field in ("backup_id", "last_success_backup_id"):
        value = payload[field]
        if not isinstance(value, str) or not (
            value == "" or re.fullmatch(r"20\d{2}-[01]\d-[0-3]\dT[0-2]\d[0-5]\d[0-5]\dZ", value)
        ):
            raise ValueError("Offsite backup identifier is invalid")
    commit = payload["source_git_commit"]
    if not isinstance(commit, str) or not (commit == "" or re.fullmatch(r"[0-9a-f]{40}", commit)):
        raise ValueError("Offsite source release is invalid")
    if not isinstance(payload["local_verified"], bool):
        raise ValueError("Offsite local verification is invalid")
    if isinstance(payload["encrypted_bytes"], bool) or not isinstance(payload["encrypted_bytes"], int):
        raise ValueError("Offsite encrypted size is invalid")
    sha = payload["ciphertext_sha256"]
    if not isinstance(sha, str) or not (sha == "" or re.fullmatch(r"[0-9a-f]{64}", sha)):
        raise ValueError("Offsite ciphertext checksum is invalid")
    for field, pattern in (
        ("age_key_version", r"[a-z0-9][a-z0-9._-]{0,63}"),
        ("remote_provider", r"[a-z0-9][a-z0-9._-]{0,79}"),
        ("remote_bucket_identifier", r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}"),
        ("error_code", r"[a-z0-9][a-z0-9_-]{0,63}"),
    ):
        value = payload[field]
        if not isinstance(value, str) or not (value == "" or re.fullmatch(pattern, value)):
            raise ValueError(f"Offsite {field} is invalid")
    prefix = payload["remote_object_prefix"]
    if not isinstance(prefix, str) or not (
        prefix == "" or re.fullmatch(r"production/20\d{2}-[01]\d-[0-3]\dT[0-2]\d[0-5]\d[0-5]\dZ/", prefix)
    ):
        raise ValueError("Offsite object prefix is invalid")
    if (
        payload["object_lock_verified"] is not None
        and type(payload["object_lock_verified"]) is not bool
    ):
        raise ValueError("Offsite Object Lock state is invalid")
    return payload


def read_source() -> dict:
    descriptor = os.open(SOURCE, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_SOURCE_BYTES:
            raise ValueError("Offsite status source is invalid")
        with os.fdopen(descriptor, "rb", closefd=False) as source:
            content = source.read(MAX_SOURCE_BYTES + 1)
        if len(content) > MAX_SOURCE_BYTES:
            raise ValueError("Offsite status source is too large")
        return validate(json.loads(content.decode("utf-8")))
    finally:
        os.close(descriptor)


def _show(unit: str, properties: tuple[str, ...]) -> dict[str, str]:
    completed = subprocess.run(
        ["systemctl", "show", unit, *[f"--property={item}" for item in properties], "--no-pager"],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    values = {}
    for line in completed.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator and key in properties:
            values[key] = value
    if set(values) != set(properties):
        raise ValueError("Incomplete systemd status")
    return values


def _enabled(unit: str) -> bool:
    completed = subprocess.run(
        ["systemctl", "is-enabled", unit],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    return completed.returncode == 0 and completed.stdout.strip() == "enabled"


def systemd_status() -> dict:
    result = {}
    for key, unit in SERVICES.items():
        values = _show(unit, ("Result", "ExecMainStatus", "ActiveState"))
        result[f"{key}_service_ok"] = (
            values["Result"] == "success"
            and values["ExecMainStatus"] == "0"
            and values["ActiveState"] != "failed"
        )
    for key, unit in TIMERS.items():
        values = _show(unit, ("ActiveState",))
        result[f"{key}_timer_enabled"] = _enabled(unit)
        result[f"{key}_timer_active"] = values["ActiveState"] == "active"
    return result


def unavailable() -> dict:
    return {
        "format_version": 1,
        "available": False,
        "last_success_at": "",
        "status": "failed",
        "last_success_backup_id": "",
        "age_key_version": "",
        "local_verified": False,
        "object_lock_verified": None,
        "error_code": "status_unavailable",
    }


def payload() -> dict:
    try:
        source = read_source()
        result = {
            "format_version": 1,
            "available": True,
            "last_success_at": source["last_success_at"],
            "status": source["status"],
            "last_success_backup_id": source["last_success_backup_id"],
            "age_key_version": source["age_key_version"],
            "local_verified": source["local_verified"],
            "object_lock_verified": source["object_lock_verified"],
            "error_code": source["error_code"],
        }
    except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        result = unavailable()
    try:
        result.update(systemd_status())
    except (OSError, ValueError, subprocess.SubprocessError):
        result.update({
            "uploader_service_ok": False,
            "finalizer_service_ok": False,
            "uploader_timer_enabled": False,
            "uploader_timer_active": False,
            "finalizer_timer_enabled": False,
            "finalizer_timer_active": False,
        })
    return result


def publish(value: dict) -> None:
    TARGET.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".offsite-status.", suffix=".tmp", dir=TARGET.parent
    )
    temporary = Path(temporary_name)
    try:
        os.chmod(temporary, 0o644)
        content = json.dumps(value, separators=(",", ":"), sort_keys=True).encode() + b"\n"
        with os.fdopen(descriptor, "wb", closefd=False) as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, TARGET)
        os.chmod(TARGET, 0o644)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def main() -> None:
    publish(payload())


if __name__ == "__main__":
    main()
