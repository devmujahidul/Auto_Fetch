import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


FETCH_SCRIPT = Path(__file__).with_name("fetch_channels.py")
STATUS_FILE = Path(__file__).with_name("fetch_status.json")
BACKUP_INTERVAL_MINUTES = int(os.environ.get("BACKUP_SCHEDULER_INTERVAL_MINUTES", "15"))
MAX_ALLOWED_DELAY_HOURS = float(os.environ.get("BACKUP_SCHEDULER_MAX_DELAY_HOURS", "2"))


def load_status() -> dict:
    if not STATUS_FILE.exists():
        return {}
    try:
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"Could not read {STATUS_FILE.name}: {exc}")
        return {}


def parse_timestamp(value: str):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def get_last_success_time():
    status = load_status()
    if status.get("status") != "success":
        return None

    timestamp = parse_timestamp(status.get("timestamp", ""))
    if timestamp is not None:
        return timestamp

    if not STATUS_FILE.exists():
        return None

    return datetime.fromtimestamp(STATUS_FILE.stat().st_mtime)


def job_is_overdue() -> bool:
    last_success = get_last_success_time()
    if last_success is None:
        logger.info("No successful fetch has been recorded yet; running backup fetch now.")
        return True

    overdue_after = timedelta(hours=MAX_ALLOWED_DELAY_HOURS)
    age = datetime.now() - last_success
    if age >= overdue_after:
        logger.warning(
            f"Last successful fetch was {age}; backup fetch will run now to close the gap."
        )
        return True

    logger.info(
        f"Last successful fetch was {age} ago; no backup run needed yet."
    )
    return False


def run_fetch() -> int:
    if not FETCH_SCRIPT.exists():
        logger.error(f"Missing fetch script: {FETCH_SCRIPT}")
        return 1

    logger.info("Launching fetch job from backup scheduler...")
    completed = subprocess.run([sys.executable, str(FETCH_SCRIPT)], check=False)
    logger.info(f"Fetch job finished with exit code {completed.returncode}")
    return completed.returncode


def main() -> int:
    logger.info("Starting backup scheduler check")
    logger.info(
        f"Backup interval: every {BACKUP_INTERVAL_MINUTES} minutes, max allowed delay: {MAX_ALLOWED_DELAY_HOURS} hours"
    )

    if job_is_overdue():
        return run_fetch()

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)