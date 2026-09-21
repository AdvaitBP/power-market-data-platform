"""Bounded request planning and compact task results, without a Flyte dependency."""

from dataclasses import dataclass, field
from datetime import date, timedelta
from uuid import UUID, uuid5

from power_market_data.domain import TRADING_HUBS
from power_market_data.warehouse.model import Request, WarehouseError, validate_run_id

MAX_DAYS = 7


@dataclass(frozen=True)
class Unit:
    day: str
    product: str
    location: str
    run_id: str

    def request(self) -> Request:
        return Request(self.product, date.fromisoformat(self.day), self.location or None)

    @property
    def label(self) -> str:
        return f"{self.day}/{self.product}/{self.location or 'CAISO'}"


@dataclass(frozen=True)
class Backfill:
    # ISO dates keep the CLI and Flyte boundary unambiguous on both platforms.
    backfill_id: str
    start_date: str
    end_date: str
    ingest_lmp: bool = True
    ingest_load: bool = True
    locations: list[str] = field(default_factory=lambda: ["TH_NP15_GEN-APND"])
    run_dbt: bool = True
    concurrency: int = 1


def expand(spec: Backfill) -> list[Unit]:
    """Inclusive Pacific dates; validate the entire plan before external I/O."""
    validate_run_id(spec.backfill_id)
    try:
        start, end = date.fromisoformat(spec.start_date), date.fromisoformat(spec.end_date)
    except ValueError as exc:
        raise WarehouseError("dates must be ISO YYYY-MM-DD") from exc
    if str(start) != spec.start_date or str(end) != spec.end_date:
        raise WarehouseError("dates must be ISO YYYY-MM-DD")
    if start > end or (end - start).days >= MAX_DAYS:
        raise WarehouseError("backfill must contain 1 through 7 inclusive Pacific days")
    if spec.concurrency != 1:
        raise WarehouseError("concurrency must be 1: raw commits share a finalization guard")
    if not spec.ingest_lmp and not spec.ingest_load:
        raise WarehouseError("select at least one product")
    if any(hub not in TRADING_HUBS for hub in spec.locations):
        raise WarehouseError("unsupported LMP hub")
    if len(set(spec.locations)) != len(spec.locations):
        raise WarehouseError("duplicate LMP hub")
    if spec.ingest_lmp and not spec.locations:
        raise WarehouseError("LMP requires at least one hub")
    units = []
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        requests = (
            [Request("lmp", day, hub) for hub in sorted(spec.locations)] if spec.ingest_lmp else []
        )
        if spec.ingest_load:
            request = Request("load", day)
            begin, finish = request.bounds
            if finish - begin > timedelta(days=1):
                raise WarehouseError("Phase 1 load source does not support Pacific fall-back days")
            requests.append(request)
        for request in requests:
            run_id = uuid5(UUID(spec.backfill_id), "backfill-unit/v1:" + request.request_id).hex
            units.append(Unit(str(day), request.product, request.location or "", run_id))
    return units


@dataclass(frozen=True)
class IngestionResult:
    unit: Unit
    status: str
    accepted_rows: int
    new_contents: int
    new_transitions: int
    reused_success: bool = False


@dataclass(frozen=True)
class DbtResult:
    status: str
    exit_code: int
    result_count: int
    log_path: str


@dataclass(frozen=True)
class VerificationResult:
    status: str
    request_counts: dict[str, int]
    bytes_processed: int = 0
    bytes_billed: int = 0


@dataclass(frozen=True)
class BackfillReport:
    backfill_id: str
    start_date: str
    end_date: str
    ingestions: list[IngestionResult]
    dbt: DbtResult
    verification: VerificationResult

    def text(self) -> str:
        lines = [f"Backfill {self.backfill_id}", f"{self.start_date} through {self.end_date}"]
        for product in ("lmp", "load"):
            rows = [r for r in self.ingestions if r.unit.product == product]
            lines.append(
                f"{product.upper()}: successful requests={len(rows)}, failed requests=0, "
                f"accepted rows={sum(r.accepted_rows for r in rows)}, "
                f"new contents={sum(r.new_contents for r in rows)}, "
                f"new transitions={sum(r.new_transitions for r in rows)}, "
                f"reused successes={sum(r.reused_success for r in rows)}"
            )
        lines.extend([f"dbt: {self.dbt.status}", f"verification: {self.verification.status}"])
        return "\n".join(lines)
