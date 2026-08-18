import hashlib
import uuid

from sqlalchemy import func, select

from app.cli import seed_monitoring
from app.models import Collector, Environment, Product, Target


def test_monitoring_seed_is_complete_and_idempotent(monkeypatch, db):
    environment_id = uuid.uuid4()
    collector_id = uuid.uuid4()
    collector_secret = "seed-test-secret-that-is-long-enough"
    observer_id = uuid.uuid4()
    observer_secret = "observer-test-secret-that-is-long-enough"
    monkeypatch.setenv("COCKPIT_MONITORING_ENVIRONMENT_ID", str(environment_id))
    monkeypatch.setenv("COCKPIT_MONITORING_COLLECTOR_ID", str(collector_id))
    monkeypatch.setenv("COCKPIT_MONITORING_COLLECTOR_SECRET", collector_secret)
    monkeypatch.setenv("COCKPIT_MONITORING_OBSERVER_ID", str(observer_id))
    monkeypatch.setenv("COCKPIT_MONITORING_OBSERVER_SECRET", observer_secret)

    seed_monitoring()
    seed_monitoring()
    db.expire_all()

    environment = db.get(Environment, environment_id)
    collector = db.get(Collector, collector_id)
    observer = db.get(Collector, observer_id)
    assert environment is not None
    assert environment.code == "production"
    assert collector is not None
    assert collector.environment_id == environment_id
    assert collector.secret_hash == hashlib.sha256(collector_secret.encode()).hexdigest()
    assert observer is not None
    assert observer.environment_id == environment_id
    assert observer.secret_hash == hashlib.sha256(observer_secret.encode()).hexdigest()
    assert db.scalar(select(func.count()).select_from(Product)) == 1
    assert db.scalar(select(func.count()).select_from(Environment)) == 1
    assert db.scalar(select(func.count()).select_from(Collector)) == 2
    assert db.scalar(select(func.count()).select_from(Target)) == 12
