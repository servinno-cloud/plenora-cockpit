import json
from pathlib import Path

from server import Handler, authorized


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


def test_observer_auth_uses_required_scoped_token(monkeypatch):
    monkeypatch.setenv("OBSERVER_TOKEN", "x" * 32)
    assert authorized("Bearer " + "x" * 32)
    assert not authorized(None)
    assert not authorized("Bearer wrong")


def test_mutating_methods_share_the_closed_405_handler():
    assert Handler.do_PUT is Handler.do_POST
    assert Handler.do_PATCH is Handler.do_POST
    assert Handler.do_DELETE is Handler.do_POST
    source = Path(__file__).parents[1].joinpath("server.py").read_text()
    for forbidden in ("subprocess", "os.system", "Popen"):
        assert forbidden not in source
