from typing import Literal, Protocol, TypedDict


class Observation(TypedDict):
    target: str
    signal: str
    source: str
    observed_at: str
    state: Literal["HEALTHY", "DEGRADED", "WARNING", "CRITICAL", "UNKNOWN"]
    code: str


class Snapshot(TypedDict):
    schema: Literal["snapshot.v1"]
    snapshot_id: str
    collector_id: str
    environment_id: str
    sequence: int
    generated_at: str
    collector_version: str
    observations: list[Observation]


class CollectorCredential(Protocol):
    @property
    def certificate_path(self) -> str: ...

    @property
    def private_key_path(self) -> str: ...


class SnapshotTransport(Protocol):
    def send(self, snapshot: Snapshot, credential: CollectorCredential) -> None: ...
