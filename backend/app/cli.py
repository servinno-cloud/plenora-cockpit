import argparse
import getpass
import hashlib
import os
import time
import uuid

from sqlalchemy import func, select

from .auth import hash_password
from .config import get_settings
from .database import SessionLocal
from .models import (
    Collector,
    Environment,
    HealthState,
    NotificationDeliveryState,
    NotificationEvent,
    NotificationEventType,
    Operator,
    OperatorRole,
    Product,
    Target,
)


def create_owner(email: str, password: str) -> None:
    normalized = email.strip().casefold()
    if not normalized or "@" not in normalized:
        raise SystemExit("A valid owner email is required")
    if len(password) < 14:
        raise SystemExit("Owner password must contain at least 14 characters")
    with SessionLocal.begin() as db:
        if db.scalar(select(func.count()).select_from(Operator)):
            raise SystemExit("An operator already exists; bootstrap refused")
        db.add(
            Operator(
                email=normalized,
                password_hash=hash_password(password),
                role=OperatorRole.OWNER,
                active=True,
            )
        )
    print("OWNER created")


def seed_monitoring() -> None:
    environment_id = uuid.UUID(os.environ["COCKPIT_MONITORING_ENVIRONMENT_ID"])
    collector_id = uuid.UUID(os.environ["COCKPIT_MONITORING_COLLECTOR_ID"])
    secret = os.environ["COCKPIT_MONITORING_COLLECTOR_SECRET"]
    if len(secret) < 32:
        raise SystemExit("Collector secret must contain at least 32 characters")
    with SessionLocal.begin() as db:
        product = db.scalar(select(Product).where(Product.code == "plenora"))
        if not product:
            product = Product(code="plenora", name="Plenora")
            db.add(product)
            db.flush()
        environment = db.get(Environment, environment_id)
        if not environment:
            environment = Environment(
                id=environment_id, product_id=product.id, code="production", name="Production"
            )
            db.add(environment)
            db.flush()
        targets = (
            ("web", "Web", "Web"),
            ("backups", "Backups", "Backups"),
            ("host", "Host", "Host"),
            ("database", "Database", "Database"),
            ("mail", "Mail", "Mail"),
            ("backend", "Backend", "Backend"),
            ("caddy", "Caddy", "Services"),
            ("frontend", "Frontend", "Services"),
            ("db", "PostgreSQL", "Services"),
            ("mail-worker", "Mail worker", "Services"),
            ("collector", "Collector", "Collector"),
            ("observer", "Plenora observer", "Observer"),
        )
        for key, name, component in targets:
            if not db.scalar(
                select(Target).where(Target.environment_id == environment.id, Target.key == key)
            ):
                db.add(
                    Target(environment_id=environment.id, key=key, name=name, component=component)
                )
        collector = db.get(Collector, collector_id)
        secret_hash = hashlib.sha256(secret.encode()).hexdigest()
        if collector:
            collector.secret_hash = secret_hash
            collector.active = True
        else:
            db.add(
                Collector(
                    id=collector_id,
                    environment_id=environment.id,
                    name="compose-local",
                    secret_hash=secret_hash,
                    active=True,
                )
            )
        observer_id = os.getenv("COCKPIT_MONITORING_OBSERVER_ID")
        observer_secret = os.getenv("COCKPIT_MONITORING_OBSERVER_SECRET")
        if observer_id or observer_secret:
            if not observer_id or not observer_secret or len(observer_secret) < 32:
                raise SystemExit("Observer identity and 32-character secret are both required")
            identity = uuid.UUID(observer_id)
            existing = db.get(Collector, identity)
            observer_hash = hashlib.sha256(observer_secret.encode()).hexdigest()
            if existing:
                existing.secret_hash = observer_hash
                existing.active = True
            else:
                db.add(
                    Collector(
                        id=identity,
                        environment_id=environment.id,
                        name="plenora-vps1-observer",
                        secret_hash=observer_hash,
                        active=True,
                    )
                )
    print("Monitoring seed ready")


def rotate_collector_secret() -> None:
    environment_id = uuid.UUID(os.environ["COCKPIT_ROTATION_ENVIRONMENT_ID"])
    collector_id = uuid.UUID(os.environ["COCKPIT_ROTATION_COLLECTOR_ID"])
    current_secret = os.environ["COCKPIT_ROTATION_CURRENT_SECRET"]
    new_secret = os.environ["COCKPIT_ROTATION_NEW_SECRET"]
    if min(len(current_secret), len(new_secret)) < 32 or current_secret == new_secret:
        raise SystemExit("Collector secret rotation refused")
    current_hash = hashlib.sha256(current_secret.encode()).hexdigest()
    new_hash = hashlib.sha256(new_secret.encode()).hexdigest()
    with SessionLocal.begin() as db:
        collector = db.scalar(
            select(Collector)
            .where(
                Collector.id == collector_id,
                Collector.environment_id == environment_id,
                Collector.active.is_(True),
                Collector.secret_hash == current_hash,
            )
            .with_for_update()
        )
        if not collector:
            raise SystemExit("Collector secret rotation refused")
        collector.secret_hash = new_hash
    print("Collector secret rotated")


def verify_collector_secret() -> None:
    environment_id = uuid.UUID(os.environ["COCKPIT_ROTATION_ENVIRONMENT_ID"])
    collector_id = uuid.UUID(os.environ["COCKPIT_ROTATION_COLLECTOR_ID"])
    candidate = os.environ["COCKPIT_ROTATION_CANDIDATE_SECRET"]
    candidate_hash = hashlib.sha256(candidate.encode()).hexdigest()
    with SessionLocal() as db:
        collector = db.scalar(
            select(Collector).where(
                Collector.id == collector_id,
                Collector.environment_id == environment_id,
                Collector.active.is_(True),
                Collector.secret_hash == candidate_hash,
            )
        )
    if not collector:
        raise SystemExit("Collector credential rejected")
    print("Collector credential valid")


def queue_test_notification(run_id: uuid.UUID) -> uuid.UUID:
    deduplication_key = f"test:{run_id}"
    with SessionLocal.begin() as db:
        existing = db.scalar(
            select(NotificationEvent).where(
                NotificationEvent.deduplication_key == deduplication_key
            )
        )
        if existing:
            return existing.id
        event = NotificationEvent(
            incident_id=None,
            event_type=NotificationEventType.TEST,
            deduplication_key=deduplication_key,
            from_severity=None,
            to_severity=HealthState.HEALTHY,
        )
        db.add(event)
        db.flush()
        return event.id


def wait_for_test_notification(event_id: uuid.UUID, timeout_seconds: int = 60) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        with SessionLocal() as db:
            event = db.get(NotificationEvent, event_id)
            if event and event.delivery_state == NotificationDeliveryState.SENT:
                return
            if event and event.delivery_state == NotificationDeliveryState.FAILED:
                raise SystemExit("Test notification delivery failed")
        if time.monotonic() >= deadline:
            break
        time.sleep(1)
    raise SystemExit("Test notification delivery timed out")


def test_notification() -> None:
    if not get_settings().notifications_configured:
        raise SystemExit("E-mail notifications are not configured")
    event_id = queue_test_notification(uuid.uuid4())
    wait_for_test_notification(event_id)
    print("Test notification sent")


def main() -> None:
    parser = argparse.ArgumentParser(description="Cockpit local bootstrap")
    parser.add_argument(
        "command",
        choices=[
            "create-owner",
            "seed-monitoring",
            "rotate-collector-secret",
            "verify-collector-secret",
            "test-notification",
        ],
    )
    parser.add_argument("--email", default=os.getenv("COCKPIT_BOOTSTRAP_EMAIL", ""))
    args = parser.parse_args()
    if args.command == "seed-monitoring":
        seed_monitoring()
    elif args.command == "rotate-collector-secret":
        rotate_collector_secret()
    elif args.command == "verify-collector-secret":
        verify_collector_secret()
    elif args.command == "test-notification":
        test_notification()
    else:
        password = os.getenv("COCKPIT_BOOTSTRAP_PASSWORD") or getpass.getpass("Owner password: ")
        create_owner(args.email, password)


if __name__ == "__main__":
    main()
