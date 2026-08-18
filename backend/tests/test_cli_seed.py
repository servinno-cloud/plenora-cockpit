import hashlib
import uuid

from sqlalchemy import func, select

from app.cli import seed_monitoring
from app.models import Collector, Environment, Product, Target


def test_monitoring_seed_is_complete_and_idempotent(monkeypatch, db):
    environment_id = uuid.uuid4()
    collector_id = uuid.uuid4()
    collector_secret = "seed-test-secret-that-is-long-enough"
    monkeypatch.setenv("COCKPIT_MONITORING_ENVIRONMENT_ID", str(environment_id))
    monkeypatch.setenv("COCKPIT_MONITORING_COLLECTOR_ID", str(collector_id))
    monkeypatch.setenv("COCKPIT_MONITORING_COLLECTOR_SECRET", collector_secret)

    seed_monitoring()
    seed_monitoring()
    db.expire_all()

    environment = db.get(Environment, environment_id)
    collector = db.get(Collector, collector_id)
    assert environment is not None
    assert environment.code == "production"
    assert collector is not None
    assert collector.environment_id == environment_id
    assert collector.secret_hash == hashlib.sha256(collector_secret.encode()).hexdigest()
    assert db.scalar(select(func.count()).select_from(Product)) == 1
    assert db.scalar(select(func.count()).select_from(Environment)) == 1
    assert db.scalar(select(func.count()).select_from(Collector)) == 1
    assert db.scalar(select(func.count()).select_from(Target)) == 12
