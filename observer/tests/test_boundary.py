import json
from pathlib import Path


def test_fixtures_are_closed_and_privacy_safe():
    mounted = Path("/fixtures")
    root = mounted if mounted.exists() else Path(__file__).parents[1] / "fixtures"
    combined = " ".join(path.read_text() for path in root.glob("*.json")).lower()
    for forbidden in ("recipient", "subject", "body", "token", "environment", "mount"):
        assert forbidden not in combined
    services = json.loads((root / "services.json").read_text())
    assert {item["key"] for item in services["services"]} == {
        "caddy",
        "frontend",
        "backend",
        "db",
        "mail-worker",
    }
