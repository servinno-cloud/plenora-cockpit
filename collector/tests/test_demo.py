from src.demo import empty_snapshot


def test_demo_snapshot_is_explicitly_empty() -> None:
    snapshot = empty_snapshot("collector", "environment")
    assert snapshot["schema"] == "snapshot.v1"
    assert snapshot["observations"] == []
