import pytest
from pydantic import ValidationError

from app.config import Settings


def values(**overrides):
    base = {
        "database_url": "sqlite:///test.sqlite3",
        "secret_key": "x" * 32,
        "env": "production",
        "allowed_origins": "https://cockpit.plenora.nl",
        "allowed_hosts": "cockpit.plenora.nl",
        "cookie_secure": True,
        "infrastructure_mode": "live",
    }
    return base | overrides


def test_production_requires_https_origin_and_secure_cookie():
    with pytest.raises(ValidationError, match="HTTPS origin"):
        Settings(**values(allowed_origins=""))
    with pytest.raises(ValidationError, match="HTTPS"):
        Settings(**values(allowed_origins="http://cockpit.plenora.nl"))
    with pytest.raises(ValidationError, match="Secure cookies"):
        Settings(**values(cookie_secure=False))


def test_production_forbids_fixture_mode():
    with pytest.raises(ValidationError, match="Fixture infrastructure"):
        Settings(**values(infrastructure_mode="fixture"))


def test_no_registration_or_remediation_routes(client):
    for path in ("/api/register", "/api/restart", "/api/deploy", "/api/restore"):
        assert client.post(path, json={}).status_code == 404
