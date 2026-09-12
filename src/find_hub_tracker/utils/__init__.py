from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def format_distance(meters: float) -> str:
    """Format a distance in meters to a human-readable string."""
    if meters < 1000:
        return f"{meters:.0f}m"
    return f"{meters / 1000:.1f}km"


def relative_time(dt: datetime) -> str:
    """Format a timestamp as a human-readable relative time string.

    Discord has native <t:...:R> relative timestamps; Telegram has no
    equivalent, so this renders the delta as plain text.
    """
    now = datetime.now(dt.tzinfo)
    delta = now - dt
    seconds = int(delta.total_seconds())

    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"
