from datetime import datetime, timezone

def utcnow() -> datetime:
    """Returns the current time in UTC, timezone aware."""
    return datetime.now(timezone.utc)

def to_timestamp(dt: datetime) -> float:
    """Converts a datetime object to a float timestamp."""
    return dt.timestamp()
