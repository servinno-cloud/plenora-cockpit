import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.auth import hash_password
from app.cli import create_owner
from app.models import AuditEvent, Operator, OperatorRole, Product


def owner(db):
    operator = Operator(
        email="owner@example.com",
        password_hash=hash_password("A-strong-foundation-password!"),
        role=OperatorRole.OWNER,
        active=True,
    )
    db.add(operator)
    db.commit()
    return operator


def csrf(client):
    response = client.get("/api/auth/csrf")
    return response.json()["csrf_token"]


def login(client):
    token = csrf(client)
    return client.post(
        "/api/auth/login",
        headers={"X-CSRF-Token": token},
        json={"email": "owner@example.com", "password": "A-strong-foundation-password!"},
    )


def test_health_checks_database(client):
    assert client.get("/health").json() == {
        "status": "healthy",
        "database": "up",
        "release": "development",
    }


def test_product_code_is_unique(db):
    db.add(Product(code="plenora", name="Plenora"))
    db.commit()
    db.add(Product(code="plenora", name="Duplicate"))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    else:
        raise AssertionError("duplicate product code was accepted")


def test_login_session_logout_and_audit(client, db):
    owner(db)
    response = login(client)
    assert response.status_code == 200
    assert response.json()["operator"]["role"] == "OWNER"
    assert client.get("/api/me").status_code == 200

    token = client.cookies.get("cockpit_csrf")
    response = client.post("/api/auth/logout", headers={"X-CSRF-Token": token})
    assert response.status_code == 200
    assert client.get("/api/me").status_code == 401
    db.expire_all()
    assert [
        event.success for event in db.scalars(select(AuditEvent).order_by(AuditEvent.created_at))
    ] == [True, True]


def test_invalid_login_is_generic_and_audited(client, db):
    owner(db)
    token = csrf(client)
    response = client.post(
        "/api/auth/login",
        headers={"X-CSRF-Token": token},
        json={"email": "owner@example.com", "password": "wrong-password"},
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid credentials"}
    event = db.scalar(select(AuditEvent))
    assert event and not event.success and event.subject_hash
    assert "owner" not in event.subject_hash


def test_login_and_logout_require_csrf(client, db):
    owner(db)
    assert (
        client.post(
            "/api/auth/login",
            json={"email": "owner@example.com", "password": "A-strong-foundation-password!"},
        ).status_code
        == 403
    )
    assert login(client).status_code == 200
    assert client.post("/api/auth/logout").status_code == 403


def test_private_api_rejects_unauthenticated_and_registration_does_not_exist(client):
    for path in ("/api/me", "/api/products", "/api/environments", "/api/incidents"):
        assert client.get(path).status_code == 401
    assert client.post("/api/register", json={}).status_code == 404


def test_owner_bootstrap_is_single_use(db):
    create_owner("first-owner@example.com", "A-different-strong-password!")
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(Operator)) == 1
    with pytest.raises(SystemExit, match="bootstrap refused"):
        create_owner("second-owner@example.com", "Another-strong-password!")
