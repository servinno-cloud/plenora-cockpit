import logging
import time
from pathlib import Path

from .analysis import process_pending
from .config import get_settings
from .database import SessionLocal
from .logging import configure_logging


def run() -> None:
    configure_logging()
    settings = get_settings()
    logging.getLogger("cockpit.analysis").info(
        "analysis_worker_started", extra={"enabled": settings.analysis_enabled}
    )
    while True:
        with SessionLocal() as db:
            process_pending(db, settings)
        Path("/tmp/analysis-worker-heartbeat").touch()
        time.sleep(15)


if __name__ == "__main__":
    run()
