"""Strict mart row boundary; no DataFrames or source response schemas."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from power_market_data.domain import TRADING_HUBS
from power_market_data.errors import ValidationError
from power_market_data.optimization.model import PriceInterval
from power_market_data.time import PACIFIC
from power_market_data.warehouse.model import CONTENT_SCHEMA, KEY_SCHEMA, Request

COLUMNS = (
    "source",
    "market",
    "unit",
    "market_date",
    "location",
    "interval_start_utc",
    "interval_end_utc",
    "lmp",
    "logical_key",
    "content_id",
    "content_hash",
    "logical_key_schema",
    "content_hash_schema",
    "transition_id",
    "state_run_id",
    "state_ordinal",
    "commit_sequence",
    "first_seen_at",
    "state_known_at",
)


@dataclass(frozen=True)
class MarketPrice:
    interval: PriceInterval
    market_date: date
    location: str
    logical_key: str
    content_id: str
    content_hash: str
    transition_id: str
    state_run_id: str
    state_ordinal: int
    commit_sequence: int
    first_seen_at: datetime
    state_known_at: datetime

    def __post_init__(self) -> None:
        if self.location not in TRADING_HUBS:
            raise ValidationError("unknown LMP hub")
        if self.interval.start_utc.astimezone(PACIFIC).date() != self.market_date:
            raise ValidationError("market_date must be the Pacific interval-start date")
        for value in (
            self.logical_key,
            self.content_id,
            self.content_hash,
            self.transition_id,
            self.state_run_id,
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValidationError("input lineage identifiers must be nonempty strings")
        for ordinal in (self.state_ordinal, self.commit_sequence):
            if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 1:
                raise ValidationError("input state ordering must be a positive integer")
        for clock in (self.first_seen_at, self.state_known_at):
            if (
                not isinstance(clock, datetime)
                or clock.tzinfo is None
                or clock.utcoffset() != timedelta(0)
            ):
                raise ValidationError("knowledge timestamps must be aware UTC")
        # Ordering uses persisted ordinals, not timestamp comparisons (ADR 004).


def from_row(row: Mapping[str, object]) -> MarketPrice:
    missing = set(COLUMNS) - row.keys()
    if missing or any(row[column] is None for column in COLUMNS):
        raise ValidationError(f"optimization input has missing/null fields: {sorted(missing)}")
    for field, expected in (
        ("source", "CAISO"),
        ("market", "DAY_AHEAD_HOURLY"),
        ("unit", "USD/MWh"),
        ("logical_key_schema", KEY_SCHEMA),
        ("content_hash_schema", CONTENT_SCHEMA),
    ):
        if row[field] != expected:
            raise ValidationError(f"optimization input {field} must equal {expected}")

    def timestamp(field: str) -> datetime:
        value = row[field]
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            return datetime.fromisoformat(value)
        raise ValidationError(f"{field} must be an ISO timestamp or datetime")

    def text(field: str) -> str:
        value = row[field]
        if not isinstance(value, str):
            raise ValidationError(f"{field} must be a string")
        return value

    def integer(field: str) -> int:
        value = row[field]
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValidationError(f"{field} must be an integer")
        return value

    try:
        raw_date = row["market_date"]
        day = date.fromisoformat(raw_date) if isinstance(raw_date, str) else raw_date
        if not isinstance(day, date) or isinstance(day, datetime):
            raise ValidationError("market_date must be a calendar date")
        raw_price = row["lmp"]
        if not isinstance(raw_price, (str, Decimal)):
            raise ValidationError("lmp must be Decimal or an exact decimal string")
        return MarketPrice(
            interval=PriceInterval(
                timestamp("interval_start_utc"), timestamp("interval_end_utc"), Decimal(raw_price)
            ),
            market_date=day,
            location=text("location"),
            logical_key=text("logical_key"),
            content_id=text("content_id"),
            content_hash=text("content_hash"),
            transition_id=text("transition_id"),
            state_run_id=text("state_run_id"),
            state_ordinal=integer("state_ordinal"),
            commit_sequence=integer("commit_sequence"),
            first_seen_at=timestamp("first_seen_at"),
            state_known_at=timestamp("state_known_at"),
        )
    except (ValueError, InvalidOperation) as exc:
        raise ValidationError(f"malformed optimization input: {exc}") from exc


def requests(start: date, end: date, location: str) -> tuple[Request, ...]:
    if (
        not isinstance(start, date)
        or not isinstance(end, date)
        or isinstance(start, datetime)
        or isinstance(end, datetime)
    ):
        raise ValidationError("backtest boundaries must be calendar dates")
    days = (end - start).days + 1
    if not 1 <= days <= 7:
        raise ValidationError("backtest requires 1 through 7 inclusive Pacific days")
    return tuple(Request("lmp", start + timedelta(days=i), location) for i in range(days))
