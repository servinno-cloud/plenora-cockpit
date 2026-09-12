import logging
import time
from pathlib import Path

from .config import get_settings
from .database import SessionLocal
from .logging import configure_logging
from .self_monitoring import run_self_monitoring

HEARTBEAT_PATH = Path("/tmp/self-monitoring-worker-heartbeat")


def run() -> None:
    configure_logging()
    settings = get_settings()
    logger = logging.getLogger("cockpit.self_monitoring")
    logger.info("self_monitoring_worker_started")
    while True:
        with SessionLocal() as db:
            observed = run_self_monitoring(db, settings)
        HEARTBEAT_PATH.touch()
        logger.info("self_monitoring_cycle_completed", extra={"observations": observed})
        time.sleep(settings.self_monitor_interval_seconds)


if __name__ == "__main__":
    run()
