import logging
import sys
import json
from pathlib import Path
from datetime import datetime

def setup_logger(name="outreach_service", level=logging.INFO):
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger

def write_run_log(log_data: dict) -> Path:
    """Write a JSON run log to the logs/ directory and return the path.
    The directory is created if missing.
    """
    logs_dir = Path(__file__).resolve().parent.parent / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    log_file = logs_dir / f"run_{timestamp}.json"
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(log_data, f, indent=2, default=str)
    return log_file

def get_latest_log() -> Path | None:
    """Return the most recent log file in the logs/ directory, or None if none exist."""
    logs_dir = Path(__file__).resolve().parent.parent / "logs"
    if not logs_dir.exists():
        return None
    files = sorted(logs_dir.glob("run_*.json"), reverse=True)
    return files[0] if files else None
