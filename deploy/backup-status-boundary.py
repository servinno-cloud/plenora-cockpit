#!/usr/bin/env python3
import json
import os
import re
import stat
import tempfile
from datetime import datetime
from pathlib import Path

SOURCE = Path("/var/backups/plenora/status.json")
TARGET = Path("/run/plenora-cockpit/backup-status.json")
MAX_SOURCE_BYTES = 16 * 1024
EXPECTED_FIELDS = {
    "last_attempt_at",
    "last_success_at",
    "status",
    "backup_id",
    "database_bytes",
    "media_bytes",
    "checksum_verified",
    "git_commit",
}


def validate(payload: object) -> dict:
    if not isinstance(payload, dict) or set(payload) != EXPECTED_FIELDS:
        raise ValueError("Backup status fields are invalid")
    for field in ("last_attempt_at", "last_success_at"):
        value = payload[field]
        if not isinstance(value, str):
            raise ValueError("Backup timestamp is invalid")
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    if payload["status"] not in {"success", "failed"}:
        raise ValueError("Backup status is invalid")
    if not isinstance(payload["backup_id"], str) or not re.fullmatch(
        r"[0-9A-Za-z._-]{1,80}", payload["backup_id"]
    ):
        raise ValueError("Backup identifier is invalid")
    for field in ("database_bytes", "media_bytes"):
        if isinstance(payload[field], bool) or not isinstance(payload[field], int):
            raise ValueError("Backup size is invalid")
        if payload[field] < 0:
            raise ValueError("Backup size is invalid")
    if not isinstance(payload["checksum_verified"], bool):
        raise ValueError("Backup checksum state is invalid")
    if not isinstance(payload["git_commit"], str) or not re.fullmatch(
        r"[0-9a-f]{7,64}", payload["git_commit"]
    ):
        raise ValueError("Backup release is invalid")
    return payload


def read_source() -> dict:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(SOURCE, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("Backup status source is not a regular file")
        if metadata.st_size > MAX_SOURCE_BYTES:
            raise ValueError("Backup status source is too large")
        with os.fdopen(descriptor, "rb", closefd=False) as source:
            content = source.read(MAX_SOURCE_BYTES + 1)
        if len(content) > MAX_SOURCE_BYTES:
            raise ValueError("Backup status source is too large")
        return validate(json.loads(content.decode("utf-8")))
    finally:
        os.close(descriptor)


def publish(payload: dict) -> None:
    TARGET.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".backup-status.", suffix=".tmp", dir=TARGET.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o644)
        content = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode() + b"\n"
        if len(content) > MAX_SOURCE_BYTES:
            raise ValueError("Validated backup status output is too large")
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
    publish(read_source())


if __name__ == "__main__":
    main()
