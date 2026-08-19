import logging
import time

from .config import get_settings
from .database import SessionLocal
from .logging import configure_logging
from .notifications import deliver_pending


def run() -> None:
    configure_logging()
    settings = get_settings()
    logging.getLogger("cockpit.notifications").info(
        "notification_worker_started",
        extra={"configured": settings.notifications_configured},
    )
    while True:
        with SessionLocal() as db:
            deliver_pending(db, settings)
        time.sleep(15)


if __name__ == "__main__":
    run()
