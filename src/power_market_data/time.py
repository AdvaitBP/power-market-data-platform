"""Explicit conversion of already-aware timestamps; never infer local offsets."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from power_market_data.errors import ValidationError

PACIFIC = ZoneInfo("America/Los_Angeles")


def as_utc(value: datetime) -> datetime:
    """Return a built-in UTC datetime, rejecting naive and nonexistent local times."""
    if not isinstance(value, datetime):
        raise ValidationError("timestamp must be a datetime")
    try:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValidationError("timestamp must include an explicit timezone/offset")
        # Round-trip catches nonexistent local times constructed with ZoneInfo.
        converted = value.astimezone(UTC)
        back = converted.astimezone(value.tzinfo)
        if back.replace(tzinfo=None) != value.replace(tzinfo=None):
            raise ValidationError("timestamp is a nonexistent local wall time")
        if back.utcoffset() != value.utcoffset():
            raise ValidationError("timestamp offset does not survive a timezone round-trip")
        # Strip third-party datetime subclasses at the boundary.
        return datetime.fromisoformat(converted.isoformat()).astimezone(UTC)
    except (ValueError, OverflowError) as exc:
        raise ValidationError(f"invalid timestamp: {exc}") from exc


def utc_text(value: datetime) -> str:
    """Canonical timestamp encoding with a fixed microsecond precision."""
    return as_utc(value).isoformat(timespec="microseconds").replace("+00:00", "Z")
