"""The only boundary that understands gridstatus's CAISO DataFrame schema."""

from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from importlib.metadata import version
from typing import Protocol, runtime_checkable

import gridstatus

from power_market_data.domain import TRADING_HUBS, LmpObservation, LoadObservation, Provenance
from power_market_data.errors import (
    SchemaError,
    UnsupportedRequestError,
    UpstreamRequestError,
    ValidationError,
)
from power_market_data.time import PACIFIC, as_utc

LMP_COLUMNS = frozenset(
    {
        "Time",
        "Interval Start",
        "Interval End",
        "Market",
        "Location",
        "Location Type",
        "LMP",
        "Energy",
        "Congestion",
        "Loss",
    }
)
LOAD_COLUMNS = frozenset({"Time", "Interval Start", "Interval End", "Load"})
OASIS_URL = "http://oasis.caiso.com/oasisapi/SingleZip"


@runtime_checkable
class _Frame(Protocol):
    """Just the two DataFrame operations used by this adapter."""

    @property
    def columns(self) -> Iterable[object]: ...

    def to_dict(self, orient: str) -> object: ...


def _rows(frame: object, required: frozenset[str]) -> list[Mapping[str, object]]:
    if not isinstance(frame, _Frame):
        raise SchemaError("expected a gridstatus DataFrame with columns and to_dict")
    try:
        columns = list(frame.columns)
    except TypeError as exc:
        raise SchemaError("upstream columns are not iterable") from exc
    if any(not isinstance(column, str) for column in columns):
        raise SchemaError("upstream column names must be strings")
    if len(columns) != len(set(columns)):
        raise SchemaError("upstream response contains duplicate columns")
    missing = required.difference(columns)
    if missing:
        raise SchemaError(f"missing required columns: {', '.join(sorted(missing))}")
    try:
        raw = frame.to_dict("records")
    except (TypeError, ValueError) as exc:
        raise SchemaError(f"upstream row conversion failed: {exc}") from exc
    if not isinstance(raw, list):
        raise SchemaError("DataFrame conversion did not produce a list of rows")
    rows: list[Mapping[str, object]] = []
    for index, row in enumerate(raw):
        if not isinstance(row, dict) or any(not isinstance(key, str) for key in row):
            raise SchemaError(f"row {index}: expected string-keyed source fields")
        if not required.issubset(row):
            raise SchemaError(f"row {index}: missing required source fields")
        rows.append(row)
    if not rows:
        raise UpstreamRequestError("CAISO returned no observations")
    return rows


def _number(value: object, name: str) -> Decimal:
    # DataFrame.to_dict converts NumPy scalars to Python int/float.
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValidationError(f"{name} must be numeric and non-null")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValidationError(f"{name} cannot be represented as a decimal") from exc
    if not result.is_finite():
        raise ValidationError(f"{name} must be finite and non-null")
    return result


def _timestamp(value: object, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValidationError(f"{name} must be a non-null timezone-aware datetime")
    if getattr(value, "nanosecond", 0):
        raise ValidationError(f"{name} has unsupported sub-microsecond precision")
    try:
        return as_utc(value)
    except ValidationError as exc:
        raise ValidationError(f"{name}: {exc}") from exc


def _times(row: Mapping[str, object]) -> tuple[datetime, datetime]:
    start = _timestamp(row["Interval Start"], "Interval Start")
    end = _timestamp(row["Interval End"], "Interval End")
    if _timestamp(row["Time"], "Time") != start:
        raise ValidationError("Time must label Interval Start in this gridstatus contract")
    return start, end


def normalize_lmp(frame: object, provenance: Provenance) -> list[LmpObservation]:
    """Validate the returned schema and convert it to domain records."""
    result: list[LmpObservation] = []
    seen: set[str] = set()
    for index, row in enumerate(_rows(frame, LMP_COLUMNS)):
        try:
            start, end = _times(row)
            location = row["Location"]
            if not isinstance(location, str) or location not in TRADING_HUBS:
                raise ValidationError("Location must be one of the supported trading hubs")
            market, location_type = row["Market"], row["Location Type"]
            if (
                not isinstance(market, str)
                or not isinstance(location_type, str)
                or market != "DAY_AHEAD_HOURLY"
                or location_type != "Trading Hub"
            ):
                raise ValidationError("expected DAY_AHEAD_HOURLY at a Trading Hub")
            record = LmpObservation(
                location=location,
                interval_start_utc=start,
                interval_end_utc=end,
                lmp=_number(row["LMP"], "LMP"),
                energy=_number(row["Energy"], "Energy"),
                congestion=_number(row["Congestion"], "Congestion"),
                loss=_number(row["Loss"], "Loss"),
                provenance=provenance,
            )
            if record.logical_key in seen:
                raise ValidationError("duplicate logical observation within response")
            seen.add(record.logical_key)
            result.append(record)
        except ValidationError as exc:
            raise ValidationError(f"LMP row {index}: {exc}") from exc
    return sorted(result, key=lambda record: (record.interval_start_utc, record.location))


def normalize_load(frame: object, provenance: Provenance) -> list[LoadObservation]:
    """Preserve the dependency's five-minute interval convention explicitly."""
    result: list[LoadObservation] = []
    seen: set[str] = set()
    for index, row in enumerate(_rows(frame, LOAD_COLUMNS)):
        try:
            start, end = _times(row)
            _check_load_day(start.astimezone(PACIFIC).date())
            record = LoadObservation(
                interval_start_utc=start,
                interval_end_utc=end,
                load=_number(row["Load"], "Load"),
                provenance=provenance,
            )
            if record.logical_key in seen:
                raise ValidationError("duplicate logical observation within response")
            seen.add(record.logical_key)
            result.append(record)
        except ValidationError as exc:
            raise ValidationError(f"load row {index}: {exc}") from exc
    return sorted(result, key=lambda record: record.interval_start_utc)


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time(), PACIFIC)
    end = datetime.combine(day + timedelta(days=1), time(), PACIFIC)
    return as_utc(start), as_utc(end)


def _check_day(day: date) -> None:
    if isinstance(day, datetime) or not isinstance(day, date):
        raise UnsupportedRequestError("request date must be a calendar date")
    if day >= datetime.now(PACIFIC).date():
        raise UnsupportedRequestError("only completed historical Pacific dates are supported")


def _check_load_day(day: date) -> None:
    start, end = _day_bounds(day)
    if end - start > timedelta(days=1):
        raise ValidationError(
            "fall-back load dates are unsupported: gridstatus 0.36.0 guesses the first "
            "offset for repeated local labels; reliable disambiguation is unavailable"
        )


def _request(call: Callable[[], object], context: str) -> object:
    try:
        return call()
    except (KeyError, TypeError) as exc:
        raise SchemaError(f"{context}: upstream parsing/schema failure: {exc}") from exc
    except Exception as exc:
        raise UpstreamRequestError(f"{context}: {type(exc).__name__}: {exc}") from exc


def _provenance(method: str, url: str) -> Provenance:
    return Provenance(
        retrieved_at_utc=datetime.now(UTC),
        source_url=url,
        source_method=method,
        library_version=version("gridstatus"),
    )


def fetch_lmp(day: date, location: str) -> list[LmpObservation]:
    """Fetch one historical Pacific day at one hub; no persistence or added retries."""
    _check_day(day)
    if location not in TRADING_HUBS:
        raise UnsupportedRequestError(f"unsupported trading hub: {location}")
    iso = gridstatus.CAISO()
    frame = _request(
        lambda: iso.get_lmp(
            date=day.isoformat(),
            end=(day + timedelta(days=1)).isoformat(),
            market=gridstatus.Markets.DAY_AHEAD_HOURLY,
            locations=[location],
        ),
        f"CAISO day-ahead LMP for {location} on {day}",
    )
    records = normalize_lmp(frame, _provenance("CAISO.get_lmp", OASIS_URL))
    start, end = _day_bounds(day)
    if any(r.location != location or not start <= r.interval_start_utc < end for r in records):
        raise ValidationError("LMP response contains observations outside the requested hub/day")
    return records


def fetch_load(day: date) -> list[LoadObservation]:
    """Fetch one historical Today’s Outlook day, except ambiguous fall-back days."""
    _check_day(day)
    _check_load_day(day)
    iso = gridstatus.CAISO()
    frame = _request(lambda: iso.get_load(date=day.isoformat()), f"CAISO load on {day}")
    url = f"https://www.caiso.com/outlook/history/{day:%Y%m%d}/demand.csv"
    records = normalize_load(frame, _provenance("CAISO.get_load", url))
    start, end = _day_bounds(day)
    if any(not start <= r.interval_start_utc < end for r in records):
        raise ValidationError("load response contains observations outside the requested day")
    return records
