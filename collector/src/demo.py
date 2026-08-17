from datetime import UTC, datetime
from uuid import uuid4

from .contracts import Snapshot


def empty_snapshot(collector_id: str, environment_id: str, sequence: int = 1) -> Snapshot:
    return {
        "schema": "snapshot.v1",
        "snapshot_id": str(uuid4()),
        "collector_id": collector_id,
        "environment_id": environment_id,
        "sequence": sequence,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "collector_version": "0.0.0-foundation",
        "observations": [],
    }
