"""Tiny synthetic raw tables; reuse Phase 2 identities without changing real CAISO data."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from power_market_data.domain import LmpObservation, LoadObservation, Observation, Provenance
from power_market_data.warehouse.model import (
    CONTENT_SCHEMA,
    KEY_SCHEMA,
    WAREHOUSE_SCHEMA,
    Latest,
    Request,
    Row,
    Snapshot,
    batch_rows,
    plan_write,
)

STEPS = ("initial", "repeat", "revision", "reappearance", "late")
FACTS = {"lmp": "fct_hourly_lmp", "load": "fct_system_load_5min"}
RAW_TABLES = (
    "ingestion_runs",
    "lmp_contents",
    "load_contents",
    "lmp_state_transitions",
    "load_state_transitions",
)


def observation(product: str, value: str, *, late: bool = False) -> Observation:
    start = datetime(2025 if late else 2026, 8, 1, 7, tzinfo=UTC)
    provenance = Provenance(
        retrieved_at_utc=datetime(2026, 9, 1, tzinfo=UTC),
        source_url="https://example.invalid/synthetic-dbt-contract",
        source_method="synthetic fixture",
        library_version="0.36.0",
    )
    if product == "lmp":
        return LmpObservation(
            location="TH_NP15_GEN-APND",
            interval_start_utc=start,
            interval_end_utc=start + timedelta(hours=1),
            lmp=Decimal(value),
            energy=Decimal("30"),
            congestion=Decimal("-2"),
            loss=Decimal("0.5"),
            provenance=provenance,
        )
    return LoadObservation(
        interval_start_utc=start,
        interval_end_utc=start + timedelta(minutes=5),
        load=Decimal(value),
        provenance=provenance,
    )


def scenario(step: str, *, ineligible: bool = True) -> dict[str, list[Row]]:
    """Cumulative A, A, B, A, old-event/new-knowledge snapshots for both products."""
    last = STEPS.index(step)
    tables: dict[str, list[Row]] = {name: [] for name in RAW_TABLES}
    for product in FACTS:
        contents: set[str] = set()
        latest: dict[str, Latest] = {}
        for index in range(last + 1):
            record = observation(product, "20" if index == 2 else "10", late=index == 4)
            request = Request(
                product,
                date(2025 if index == 4 else 2026, 8, 1),
                "TH_NP15_GEN-APND" if product == "lmp" else None,
            )
            # Sequence allocation is stable across snapshots and shared by products.
            # Reserve ten sequence numbers per step; LMP/load use separate offsets.
            sequence_id = index * 10 + (1 if product == "lmp" else 2)
            run_id = f"{sequence_id:032x}"
            plan = plan_write(
                run_id,
                batch_rows(request, [record]),
                Snapshot(sequence_id - 1, frozenset(contents), latest),
            )
            known = datetime(2026, 9, 1, tzinfo=UTC) + timedelta(minutes=sequence_id)
            tables["ingestion_runs"].append(
                {
                    "run_id": run_id,
                    "request_id": request.request_id,
                    "source": "CAISO",
                    "product": product,
                    "requested_date": request.day,
                    "requested_location": request.location,
                    "started_at": known - timedelta(seconds=1),
                    "completed_at": known,
                    "knowledge_at": known,
                    "status": "SUCCEEDED",
                    "commit_completed": True,
                    "package_version": "0.1.0",
                    "library_version": "0.36.0",
                    "warehouse_schema": WAREHOUSE_SCHEMA,
                    "logical_key_schema": KEY_SCHEMA,
                    "content_hash_schema": CONTENT_SCHEMA,
                    "rows_fetched": 1,
                    "rows_normalized": 1,
                    "rows_accepted": 1,
                    "rows_rejected": 0,
                    "new_contents": len(plan.contents),
                    "new_transitions": len(plan.transitions),
                    "batch_hash": plan.batch_hash,
                    "commit_sequence": sequence_id,
                }
            )
            for row in plan.contents:
                tables[f"{product}_contents"].append({**row, "first_seen_at": known})
                contents.add(str(row["content_id"]))
            for row in plan.transitions:
                tables[f"{product}_state_transitions"].append({**row, "known_at": known})
                latest[str(row["logical_key"])] = Latest(
                    str(row["content_hash"]),
                    int(str(row["ordinal"])),
                )
        if ineligible:
            # Adversarial consumer fixtures: correct Phase 2 normally rolls failed
            # data back. Never publish these rows into the real raw dataset.
            for offset, status in enumerate(("STARTED", "FAILED", "COMMITTED"), 100):
                run_id = f"{offset + (10 if product == 'load' else 0):032x}"
                request = Request(
                    product,
                    date(2026, 8, 1),
                    "TH_NP15_GEN-APND" if product == "lmp" else None,
                )
                plan = plan_write(
                    run_id,
                    batch_rows(request, [observation(product, str(offset))]),
                    Snapshot(offset, frozenset(contents), latest),
                )
                template = next(
                    row for row in tables["ingestion_runs"] if row["product"] == product
                )
                tables["ingestion_runs"].append(
                    {
                        **template,
                        "run_id": run_id,
                        "status": status,
                        "commit_completed": status == "COMMITTED",
                        "knowledge_at": None,
                        "completed_at": None,
                        "commit_sequence": offset + 1,
                    }
                )
                tables[f"{product}_contents"].extend(plan.contents)
                tables[f"{product}_state_transitions"].extend(plan.transitions)
    return tables
