from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from test_foundation import login, owner
from test_monitoring import payload, post, setup_monitoring

from app.config import get_settings
from app.models import (
    Incident,
    NotificationDeliveryState,
    NotificationEvent,
    NotificationEventType,
)
from app.notifications import deliver_pending


class RecordingProvider:
    def __init__(self, fails=False):
        self.messages = []
        self.fails = fails

    def send(self, message):
        self.messages.append(message)
        if self.fails:
            raise RuntimeError("synthetic provider failure")


def configured(**updates):
    values = {
        "notification_email_to": "operations@example.test",
        "notification_email_from": "cockpit@example.test",
        "notification_smtp_host": "smtp.example.test",
        "notification_max_attempts": 3,
    }
    values.update(updates)
    return get_settings().model_copy(update=values)


def test_lifecycle_outbox_is_deduplicated_and_survives_replay(client, db):
    environment, collector = setup_monitoring(db)
    start = datetime.now(UTC) - timedelta(seconds=20)
    post(client, environment, payload(environment, collector, 1, 600,
         signal="https.latency_ms", observed_at=start))
    assert db.scalar(select(func.count()).select_from(NotificationEvent)) == 0

    post(client, environment, payload(environment, collector, 2, 600,
         signal="https.latency_ms", observed_at=start + timedelta(seconds=1)))
    assert [item.event_type for item in db.scalars(select(NotificationEvent))] == [
        NotificationEventType.OPENED]

    replay = payload(environment, collector, 3, 600, signal="https.latency_ms")
    assert post(client, environment, replay).status_code == 202
    assert post(client, environment, replay).json()["status"] == "duplicate"
    assert db.scalar(select(func.count()).select_from(NotificationEvent)) == 1

    post(client, environment, payload(environment, collector, 4, 2501,
         signal="https.latency_ms"))
    post(client, environment, payload(environment, collector, 5, 2501,
         signal="https.latency_ms"))
    assert db.scalar(select(func.count()).select_from(NotificationEvent).where(
        NotificationEvent.event_type == NotificationEventType.ESCALATED)) == 1

    post(client, environment, payload(environment, collector, 6, 100,
         signal="https.latency_ms"))
    assert db.scalar(select(func.count()).select_from(NotificationEvent)) == 2
    post(client, environment, payload(environment, collector, 7, 100,
         signal="https.latency_ms"))
    post(client, environment, payload(environment, collector, 8, 100,
         signal="https.latency_ms"))
    events = list(db.scalars(select(NotificationEvent).order_by(NotificationEvent.created_at)))
    assert [item.event_type for item in events] == [
        NotificationEventType.OPENED, NotificationEventType.ESCALATED,
        NotificationEventType.RESOLVED]
    assert len({item.deduplication_key for item in events}) == 3


def test_delivery_disabled_failure_retry_limit_and_ingest_independence(client, db):
    environment, collector = setup_monitoring(db)
    for sequence in (1, 2):
        response = post(client, environment, payload(environment, collector, sequence))
        assert response.status_code == 202
    event = db.scalar(select(NotificationEvent))
    disabled = get_settings().model_copy(update={"notification_email_to": ""})
    assert deliver_pending(db, disabled, RecordingProvider()) == 0
    assert event.attempt_count == 0 and event.delivery_state == NotificationDeliveryState.PENDING

    provider = RecordingProvider(fails=True)
    settings = configured(notification_max_attempts=2)
    assert deliver_pending(db, settings, provider) == 0
    assert event.delivery_state == NotificationDeliveryState.PENDING
    assert deliver_pending(db, settings, provider) == 0
    assert event.attempt_count == 2
    assert event.delivery_state == NotificationDeliveryState.FAILED
    assert len(provider.messages) == 2
    assert post(client, environment, payload(environment, collector, 3)).status_code == 202


def test_successful_delivery_and_incident_api_auth(client, db):
    environment, collector = setup_monitoring(db)
    for sequence in (1, 2):
        post(client, environment, payload(environment, collector, sequence))
    incident = db.scalar(select(Incident))
    assert client.get("/api/incidents").status_code == 401
    assert client.get(f"/api/incidents/{incident.id}").status_code == 401
    assert client.get("/api/notification-status").status_code == 401
    provider = RecordingProvider()
    assert deliver_pending(db, configured(), provider) == 1
    event = db.scalar(select(NotificationEvent))
    assert event.delivery_state == NotificationDeliveryState.SENT
    assert "cockpit.plenora.nl/incidenten" in provider.messages[0].get_content()
    owner(db)
    assert login(client).status_code == 200
    listing = client.get("/api/incidents").json()[0]
    assert listing["product"] == "Plenora" and listing["environment"] == "Production"
    detail = client.get(f"/api/incidents/{incident.id}").json()
    assert detail["observations"] and detail["fingerprint"] == incident.fingerprint
