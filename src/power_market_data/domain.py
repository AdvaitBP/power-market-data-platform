"""Validated CAISO observations, independent of pandas and gridstatus schemas."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from power_market_data.errors import ValidationError
from power_market_data.identity import decimal_text, digest
from power_market_data.time import PACIFIC, as_utc, utc_text

TRADING_HUBS = ("TH_NP15_GEN-APND", "TH_SP15_GEN-APND", "TH_ZP26_GEN-APND")


def _canonical_time(value: datetime, name: str) -> None:
    as_utc(value)
    if value.tzinfo is not UTC:
        raise ValidationError(f"{name} must use datetime.UTC")


def _interval(start: datetime, end: datetime, duration: timedelta) -> None:
    _canonical_time(start, "interval_start_utc")
    _canonical_time(end, "interval_end_utc")
    if end - start != duration:
        raise ValidationError(f"interval must be positive and exactly {duration}")
    if start.second or start.microsecond or start.minute % (duration.seconds // 60):
        raise ValidationError("interval start is not aligned to the product frequency")


def _finite(value: Decimal, name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValidationError(f"{name} must be a finite Decimal")


@dataclass(frozen=True, slots=True, kw_only=True)
class Provenance:
    """Retrieval metadata, not a durable ingestion or knowledge-time commitment."""

    retrieved_at_utc: datetime
    source_url: str
    source_method: str
    library_version: str

    def __post_init__(self) -> None:
        _canonical_time(self.retrieved_at_utc, "retrieved_at_utc")
        if not all((self.source_url, self.source_method, self.library_version)):
            raise ValidationError("provenance fields must be present")


@dataclass(frozen=True, slots=True, kw_only=True)
class LmpObservation:
    """One CAISO day-ahead hourly price at one supported hub and UTC interval."""

    location: str
    interval_start_utc: datetime
    interval_end_utc: datetime
    lmp: Decimal
    energy: Decimal
    congestion: Decimal
    loss: Decimal
    provenance: Provenance
    source: str = field(default="CAISO", init=False)
    product: str = field(default="day_ahead_hourly_lmp", init=False)
    market: str = field(default="DAY_AHEAD_HOURLY", init=False)
    location_type: str = field(default="Trading Hub", init=False)
    unit: str = field(default="USD/MWh", init=False)
    source_dataset: str = field(default="PRC_LMP", init=False)

    def __post_init__(self) -> None:
        if self.location not in TRADING_HUBS:
            raise ValidationError(f"unsupported LMP location: {self.location}")
        _interval(self.interval_start_utc, self.interval_end_utc, timedelta(hours=1))
        for name in ("lmp", "energy", "congestion", "loss"):
            _finite(getattr(self, name), name)

    def identity_fields(self) -> dict[str, str]:
        return {
            "source": self.source,
            "product": self.product,
            "market": self.market,
            "location": self.location,
            "interval_start_utc": utc_text(self.interval_start_utc),
            "interval_end_utc": utc_text(self.interval_end_utc),
        }

    def content_fields(self) -> dict[str, str]:
        return {
            **self.identity_fields(),
            "unit": self.unit,
            "lmp": decimal_text(self.lmp),
            "energy": decimal_text(self.energy),
            "congestion": decimal_text(self.congestion),
            "loss": decimal_text(self.loss),
        }

    @property
    def logical_key(self) -> str:
        return digest("observation-key/v1", self.identity_fields())

    @property
    def content_hash(self) -> str:
        return digest("observation-content/v1", self.content_fields())


@dataclass(frozen=True, slots=True, kw_only=True)
class LoadObservation:
    """One CAISO system demand observation over one five-minute UTC interval."""

    interval_start_utc: datetime
    interval_end_utc: datetime
    load: Decimal
    provenance: Provenance
    source: str = field(default="CAISO", init=False)
    product: str = field(default="system_load_5min", init=False)
    area: str = field(default="CAISO", init=False)
    unit: str = field(default="MW", init=False)
    source_dataset: str = field(default="todays_outlook_demand", init=False)

    def __post_init__(self) -> None:
        _interval(self.interval_start_utc, self.interval_end_utc, timedelta(minutes=5))
        _finite(self.load, "load")
        if self.load < 0:
            raise ValidationError("system demand must be nonnegative; this is not net load")

    def identity_fields(self) -> dict[str, str]:
        return {
            "source": self.source,
            "product": self.product,
            "area": self.area,
            "interval_start_utc": utc_text(self.interval_start_utc),
            "interval_end_utc": utc_text(self.interval_end_utc),
        }

    def content_fields(self) -> dict[str, str]:
        return {**self.identity_fields(), "unit": self.unit, "load": decimal_text(self.load)}

    @property
    def logical_key(self) -> str:
        return digest("observation-key/v1", self.identity_fields())

    @property
    def content_hash(self) -> str:
        return digest("observation-content/v1", self.content_fields())


type Observation = LmpObservation | LoadObservation


def observation_dict(record: Observation) -> dict[str, str]:
    """A JSON-friendly view; decimal values remain strings without rounding."""
    return {
        **record.content_fields(),
        "source_dataset": record.source_dataset,
        "source_timezone": "America/Los_Angeles",
        "interval_start_pacific": record.interval_start_utc.astimezone(PACIFIC).isoformat(),
        "interval_end_pacific": record.interval_end_utc.astimezone(PACIFIC).isoformat(),
        "logical_key": record.logical_key,
        "content_hash": record.content_hash,
        "retrieved_at_utc": utc_text(record.provenance.retrieved_at_utc),
        "source_url": record.provenance.source_url,
        "source_method": record.provenance.source_method,
        "library_version": record.provenance.library_version,
    }
