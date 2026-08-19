import logging
import smtplib
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .config import Settings
from .models import (
    Environment,
    NotificationDeliveryState,
    NotificationEvent,
    NotificationEventType,
    Product,
)

logger = logging.getLogger("cockpit.notifications")


class EmailProvider(Protocol):
    def send(self, message: EmailMessage) -> None: ...


class SMTPEmailProvider:
    def __init__(self, settings: Settings):
        self.settings = settings

    def send(self, message: EmailMessage) -> None:
        with smtplib.SMTP(self.settings.notification_smtp_host,
                          self.settings.notification_smtp_port, timeout=10) as client:
            if self.settings.notification_smtp_starttls:
                client.starttls()
            if self.settings.notification_smtp_username:
                client.login(self.settings.notification_smtp_username,
                             self.settings.notification_smtp_password)
            client.send_message(message)


def _duration(start: datetime, end: datetime) -> str:
    start = start.replace(tzinfo=UTC) if start.tzinfo is None else start.astimezone(UTC)
    end = end.replace(tzinfo=UTC) if end.tzinfo is None else end.astimezone(UTC)
    seconds = max(0, int((end - start).total_seconds()))
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    return f"{hours}u {minutes}m" if hours else f"{minutes}m"


def build_message(db: Session, event: NotificationEvent, settings: Settings) -> EmailMessage:
    if event.event_type == NotificationEventType.TEST:
        message = EmailMessage()
        message["To"] = settings.notification_email_to
        message["From"] = settings.notification_email_from
        message["Subject"] = "Plenora Cockpit — testnotificatie"
        message.set_content(
            "Dit is een test van de Plenora Cockpit e-mailnotificatieketen.\n\n"
            f"{settings.public_url.rstrip('/')}/incidenten\n"
        )
        return message
    incident = event.incident
    if incident is None:
        raise ValueError("lifecycle notification is missing its incident")
    environment = db.get(Environment, incident.environment_id)
    product = db.get(Product, environment.product_id) if environment else None
    product_name = product.name if product else "Plenora"
    environment_name = environment.name if environment else ""
    context = f"{product_name} {environment_name}".strip()
    link = f"{settings.public_url.rstrip('/')}/incidenten?incident={incident.id}"
    if event.event_type == NotificationEventType.RESOLVED:
        subject = f"{context} — HERSTELD — {incident.title}"
        lead = "Incident hersteld"
    elif event.event_type == NotificationEventType.ESCALATED:
        subject = f"{context} — {event.to_severity.value} — {incident.title}"
        lead = f"Severity geëscaleerd: {event.from_severity.value} → {event.to_severity.value}"
    else:
        subject = f"{context} — {event.to_severity.value} — {incident.title}"
        lead = incident.title
    end = incident.resolved_at or incident.last_seen_at
    body = [lead, "", f"Component: {incident.component}",
            f"Sinds: {incident.first_seen_at.isoformat()}",
            f"Laatste meting: {incident.last_seen_at.isoformat()}",
            f"Incident: {incident.id}"]
    if event.event_type == NotificationEventType.RESOLVED:
        body.append(f"Totale duur: {_duration(incident.first_seen_at, end)}")
    body.extend(("", link))
    message = EmailMessage()
    message["To"] = settings.notification_email_to
    message["From"] = settings.notification_email_from
    message["Subject"] = subject
    message.set_content("\n".join(body))
    return message


def deliver_pending(db: Session, settings: Settings, provider: EmailProvider | None = None,
                    limit: int = 20) -> int:
    if not settings.notifications_configured:
        return 0
    query = (
        select(NotificationEvent)
        .options(selectinload(NotificationEvent.incident))
        .where(NotificationEvent.delivery_state == NotificationDeliveryState.PENDING)
        .order_by(NotificationEvent.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    items = list(db.scalars(query))
    sender = provider or SMTPEmailProvider(settings)
    sent = 0
    for event in items:
        event.attempt_count += 1
        event.last_attempt_at = datetime.now(UTC)
        try:
            sender.send(build_message(db, event, settings))
        except Exception:
            event.last_error_code = "provider_delivery_failed"
            if event.attempt_count >= settings.notification_max_attempts:
                event.delivery_state = NotificationDeliveryState.FAILED
            logger.warning("notification_delivery_failed", extra={"event_id": str(event.id),
                                                                   "attempt": event.attempt_count})
        else:
            event.delivery_state = NotificationDeliveryState.SENT
            event.sent_at = datetime.now(UTC)
            event.last_error_code = None
            sent += 1
        db.commit()
    return sent
