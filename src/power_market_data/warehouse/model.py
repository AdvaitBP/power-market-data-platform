"""Warehouse request, serialization and transition decisions, independent of cloud I/O."""

import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Self
from uuid import UUID

from power_market_data.domain import TRADING_HUBS, LmpObservation, Observation
from power_market_data.errors import PowerMarketDataError
from power_market_data.identity import decimal_text, digest
from power_market_data.time import PACIFIC

KEY_SCHEMA = "observation-key/v1"
CONTENT_SCHEMA = "observation-content/v1"
WAREHOUSE_SCHEMA = "warehouse/v1"
MAX_BATCH_ROWS = 300
MAX_BYTES_BILLED = 100 * 1024 * 1024
type Value = str | int | bool | date | datetime | Decimal | None
type Row = dict[str, Value]


class WarehouseError(PowerMarketDataError):
    """Configuration, persistence or reconciliation failed."""


class CommitUnconfirmed(WarehouseError):
    """A submitted job may still commit; resume its run rather than guessing."""


@dataclass(frozen=True)
class WarehouseConfig:
    project: str
    dataset: str = "power_market_raw"
    location: str = "US"
    maximum_bytes_billed: int = MAX_BYTES_BILLED

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", self.project):
            raise WarehouseError("GCP_PROJECT_ID must be an explicit valid project ID")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", self.dataset):
            raise WarehouseError("BQ_RAW_DATASET must be a simple dataset identifier")
        if not re.fullmatch(r"[A-Za-z0-9-]+", self.location):
            raise WarehouseError("BQ_LOCATION must be a BigQuery location")
        if not 1 <= self.maximum_bytes_billed <= MAX_BYTES_BILLED:
            raise WarehouseError("BQ_MAXIMUM_BYTES_BILLED must be between 1 and 104857600")

    @classmethod
    def from_environment(cls) -> Self:
        try:
            return cls(
                project=os.environ.get("GCP_PROJECT_ID", ""),
                dataset=os.environ.get("BQ_RAW_DATASET", "power_market_raw"),
                location=os.environ.get("BQ_LOCATION", "US"),
                maximum_bytes_billed=int(
                    os.environ.get("BQ_MAXIMUM_BYTES_BILLED", str(MAX_BYTES_BILLED))
                ),
            )
        except ValueError as exc:
            raise WarehouseError("BQ_MAXIMUM_BYTES_BILLED must be an integer") from exc

    def table(self, name: str) -> str:
        if not re.fullmatch(r"[a-z_]+", name):
            raise WarehouseError("invalid internal table name")
        return f"{self.project}.{self.dataset}.{name}"


@dataclass(frozen=True)
class Request:
    product: str
    day: date
    location: str | None = None

    def __post_init__(self) -> None:
        if self.product not in ("lmp", "load"):
            raise WarehouseError("warehouse product must be lmp or load")
        if isinstance(self.day, datetime) or not isinstance(self.day, date):
            raise WarehouseError("request day must be a calendar date")
        if self.day >= datetime.now(PACIFIC).date():
            raise WarehouseError("request must be a completed Pacific day")
        if self.product == "lmp" and self.location not in TRADING_HUBS:
            raise WarehouseError("LMP requires a supported trading hub")
        if self.product == "load" and self.location is not None:
            raise WarehouseError("system load does not have a requested hub")

    @property
    def bounds(self) -> tuple[datetime, datetime]:
        return (
            datetime.combine(self.day, time(), PACIFIC).astimezone(UTC),
            datetime.combine(self.day + timedelta(days=1), time(), PACIFIC).astimezone(UTC),
        )

    @property
    def request_id(self) -> str:
        return digest(
            "bounded-request/v1",
            {
                "source": "CAISO",
                "product": self.product,
                "date": str(self.day),
                "location": self.location or "",
            },
        )


def validate_run_id(run_id: str) -> str:
    try:
        if UUID(run_id).hex != run_id:
            raise ValueError
    except ValueError as exc:
        raise WarehouseError("run ID must be a UUID's 32 lowercase hexadecimal characters") from exc
    return run_id


def content_id(record: Observation) -> str:
    return digest(
        "warehouse-content/v1",
        {
            "logical_key": record.logical_key,
            "content_hash": record.content_hash,
            "logical_key_schema": KEY_SCHEMA,
            "content_hash_schema": CONTENT_SCHEMA,
        },
    )


def numeric(value: Decimal) -> Decimal:
    """Reject NUMERIC overflow or rounding; never change values behind their hashes."""
    text = decimal_text(value)
    whole, _, fraction = text.lstrip("-").partition(".")
    if len(whole.lstrip("0")) > 29 or len(fraction) > 9:
        raise WarehouseError("source decimal cannot be stored exactly as BigQuery NUMERIC(38,9)")
    return value


def batch_rows(request: Request, records: Sequence[Observation]) -> list[Row]:
    if len(records) > MAX_BATCH_ROWS:
        raise WarehouseError("batch exceeds the 300-observation daily safety limit")
    start, end = request.bounds
    rows: list[Row] = []
    seen: set[str] = set()
    for record in records:
        if isinstance(record, LmpObservation) != (request.product == "lmp"):
            raise WarehouseError("observation product differs from request")
        if not start <= record.interval_start_utc < end or record.interval_end_utc > end:
            raise WarehouseError("observation lies outside the bounded Pacific day")
        if isinstance(record, LmpObservation) and record.location != request.location:
            raise WarehouseError("observation lies outside the requested hub")
        if record.logical_key in seen:
            raise WarehouseError("duplicate logical key in batch")
        seen.add(record.logical_key)
        row: Row = dict(record.content_fields())
        row.update(
            content_id=content_id(record),
            logical_key=record.logical_key,
            content_hash=record.content_hash,
            logical_key_schema=KEY_SCHEMA,
            content_hash_schema=CONTENT_SCHEMA,
            market_date=request.day,
            interval_start_utc=record.interval_start_utc,
            interval_end_utc=record.interval_end_utc,
            retrieved_at_utc=record.provenance.retrieved_at_utc,
            source_url=record.provenance.source_url,
            source_method=record.provenance.source_method,
            library_version=record.provenance.library_version,
            source_dataset=record.source_dataset,
        )
        for name in (
            ("lmp", "energy", "congestion", "loss")
            if isinstance(record, LmpObservation)
            else ("load",)
        ):
            row[name] = numeric(getattr(record, name))
        rows.append(row)
    return sorted(rows, key=lambda row: str(row["logical_key"]))


@dataclass(frozen=True)
class Latest:
    content_hash: str
    ordinal: int


@dataclass(frozen=True)
class Snapshot:
    sequence: int
    contents: frozenset[str]
    latest: Mapping[str, Latest]


@dataclass(frozen=True)
class WritePlan:
    contents: list[Row]
    transitions: list[Row]
    batch_hash: str
    accepted: int
    expected_sequence: int


def plan_write(run_id: str, rows: Sequence[Row], snapshot: Snapshot) -> WritePlan:
    """Only a material change creates a transition; reappearance reuses content."""
    validate_run_id(run_id)
    new_contents: list[Row] = []
    transitions: list[Row] = []
    fingerprint = {}
    for row in rows:
        key, value_hash = str(row["logical_key"]), str(row["content_hash"])
        fingerprint[key] = value_hash
        if str(row["content_id"]) not in snapshot.contents:
            new_contents.append({**row, "first_run_id": run_id, "first_seen_at": None})
        latest = snapshot.latest.get(key)
        if latest is None or latest.content_hash != value_hash:
            transitions.append(
                {
                    "transition_id": digest("state-transition/v1", {"run_id": run_id, "key": key}),
                    "run_id": run_id,
                    "logical_key": key,
                    "content_id": row["content_id"],
                    "content_hash": value_hash,
                    "logical_key_schema": KEY_SCHEMA,
                    "content_hash_schema": CONTENT_SCHEMA,
                    "market_date": row["market_date"],
                    "interval_start_utc": row["interval_start_utc"],
                    "ordinal": 1 if latest is None else latest.ordinal + 1,
                    "commit_sequence": snapshot.sequence + 1,
                    "known_at": None,
                    "retrieved_at_utc": row["retrieved_at_utc"],
                }
            )
    return WritePlan(
        new_contents,
        transitions,
        digest("batch-content/v1", fingerprint),
        len(rows),
        snapshot.sequence,
    )
