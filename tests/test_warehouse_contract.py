"""Exercise production transition planning, without pretending to emulate BigQuery SQL."""

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from power_market_data.domain import LmpObservation, Observation, Provenance
from power_market_data.sources.caiso import normalize_lmp, normalize_load
from power_market_data.warehouse.model import (
    CONTENT_SCHEMA,
    KEY_SCHEMA,
    MAX_BATCH_ROWS,
    Latest,
    Request,
    Snapshot,
    WarehouseConfig,
    WarehouseError,
    batch_rows,
    numeric,
    plan_write,
    validate_run_id,
)

type Rows = Callable[[str], list[dict[str, object]]]
type Frame = Callable[[list[dict[str, object]]], object]


@pytest.mark.parametrize("product", ["lmp", "load"])
def test_repeat_revision_reappearance(
    product: str,
    rows: Rows,
    frame: Frame,
    provenance: Provenance,
) -> None:
    normalize = normalize_lmp if product == "lmp" else normalize_load
    record = normalize(frame(rows(product)), provenance)[0]
    request = Request(
        product, date(2026, 8, 1), record.location if isinstance(record, LmpObservation) else None
    )
    revised: Observation = (
        replace(record, lmp=Decimal("99"))
        if isinstance(record, LmpObservation)
        else replace(record, load=Decimal("99"))
    )
    known: set[str] = set()
    latest: dict[str, Latest] = {}
    counts = []
    ids = []
    # Apply planner output as state inputs to the next call, not a fake database.
    for seq, item in enumerate((record, record, revised, record)):
        plan = plan_write(
            uuid4().hex, batch_rows(request, [item]), Snapshot(seq, frozenset(known), dict(latest))
        )
        counts.append((len(plan.contents), len(plan.transitions)))
        for content in plan.contents:
            known.add(str(content["content_id"]))
        for transition in plan.transitions:
            latest[str(transition["logical_key"])] = Latest(
                str(transition["content_hash"]), int(str(transition["ordinal"]))
            )
            ids.append(transition["content_id"])
    assert counts == [(1, 1), (0, 0), (1, 1), (0, 1)]
    assert len(known) == 2
    assert ids[0] == ids[2] != ids[1]
    assert latest[record.logical_key].ordinal == 3


def test_replay_is_deterministic(
    rows: Rows,
    frame: Frame,
    provenance: Provenance,
) -> None:
    records = normalize_load(frame(rows("load")), provenance)
    request = Request("load", date(2026, 8, 1))
    batch = batch_rows(request, records)
    snapshot = Snapshot(7, frozenset(), {})
    run_id = uuid4().hex
    first = plan_write(run_id, batch, snapshot)
    assert first == plan_write(run_id, batch_rows(request, list(reversed(records))), snapshot)
    assert first.batch_hash == plan_write(run_id, list(reversed(batch)), snapshot).batch_hash
    competing = plan_write(uuid4().hex, batch, snapshot)
    assert competing.expected_sequence == first.expected_sequence
    assert competing.contents[0]["content_id"] == first.contents[0]["content_id"]
    assert competing.transitions[0]["transition_id"] != first.transitions[0]["transition_id"]
    # Both plans require sequence 7; SQL will accept at most one before incrementing it.
    assert first.transitions[0]["commit_sequence"] == 8


def test_late_arrival_does_not_backdate_knowledge(
    rows: Rows,
    frame: Frame,
    provenance: Provenance,
) -> None:
    record = normalize_load(frame(rows("load")), provenance)[0]
    plan = plan_write(
        uuid4().hex,
        batch_rows(Request("load", date(2026, 8, 1)), [record]),
        Snapshot(0, frozenset(), {}),
    )
    content = plan.contents[0]
    assert content["interval_start_utc"] == datetime(2026, 8, 1, 7, tzinfo=UTC)
    assert content["retrieved_at_utc"] == provenance.retrieved_at_utc
    assert content["first_seen_at"] is None  # Only a confirmed durable job supplies it.
    assert plan.transitions[0]["known_at"] is None
    assert content["logical_key_schema"] == KEY_SCHEMA
    assert content["content_hash_schema"] == CONTENT_SCHEMA


@pytest.mark.parametrize(
    "text",
    [
        "0",
        "-0.000",
        "-99999999999999999999999999999.999999999",
        "0.000000001",
        "1E+28",
        "1.230000000000",
    ],
)
def test_numeric_exact_values(text: str) -> None:
    assert numeric(Decimal(text)) == Decimal(text)


@pytest.mark.parametrize("text", ["1E29", "-1E29", "0.0000000001"])
def test_numeric_never_rounds(text: str) -> None:
    with pytest.raises(WarehouseError, match="exactly"):
        numeric(Decimal(text))


@pytest.mark.parametrize(
    "overrides",
    [
        {"project": ""},
        {"project": "a; DROP"},
        {"dataset": "other.raw"},
        {"dataset": "raw`"},
        {"location": "US; DROP"},
        {"maximum_bytes_billed": 0},
        {"maximum_bytes_billed": 104857601},
    ],
)
def test_config_rejects_unsafe_or_unbounded_values(overrides: dict[str, object]) -> None:
    with pytest.raises(WarehouseError):
        WarehouseConfig(**{"project": "valid-project", **overrides})  # type: ignore[arg-type]


@pytest.mark.parametrize("run_id", ["", "abc", "../id", str(uuid4()), "A" * 32])
def test_invalid_run_ids(run_id: str) -> None:
    with pytest.raises(WarehouseError):
        validate_run_id(run_id)


@pytest.mark.parametrize(
    "args",
    [
        ("other", date(2026, 8, 1), None),
        ("lmp", date(2026, 8, 1), "ALL"),
        ("load", date(2026, 8, 1), "TH_NP15_GEN-APND"),
        ("load", date(9999, 1, 1), None),
        ("load", datetime(2026, 8, 1), None),
    ],
)
def test_request_validation(args: tuple[str, date, str | None]) -> None:
    with pytest.raises(WarehouseError):
        Request(*args)


def test_bounded_batch_validation(rows: Rows, frame: Frame, provenance: Provenance) -> None:
    record = normalize_load(frame(rows("load")), provenance)[0]
    request = Request("load", date(2026, 8, 1))
    with pytest.raises(WarehouseError, match="duplicate"):
        batch_rows(request, [record, record])
    with pytest.raises(WarehouseError, match="safety limit"):
        batch_rows(request, [record] * (MAX_BATCH_ROWS + 1))
    with pytest.raises(WarehouseError, match="outside"):
        batch_rows(Request("load", date(2026, 8, 2)), [record])
    with pytest.raises(WarehouseError, match="product"):
        batch_rows(Request("lmp", date(2026, 8, 1), "TH_NP15_GEN-APND"), [record])


def test_successful_empty_is_explicit() -> None:
    plan = plan_write(uuid4().hex, [], Snapshot(0, frozenset(), {}))
    assert plan.accepted == 0
    assert not plan.contents and not plan.transitions
    # CAISO fetch still rejects an empty source response; only explicit normalized empty batches.


def test_environment_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GCP_PROJECT_ID", "valid-project")
    monkeypatch.setenv("BQ_MAXIMUM_BYTES_BILLED", "invalid")
    with pytest.raises(WarehouseError, match="integer"):
        WarehouseConfig.from_environment()
    monkeypatch.setenv("BQ_MAXIMUM_BYTES_BILLED", "10000000")
    assert WarehouseConfig.from_environment().maximum_bytes_billed == 10000000


def test_request_dst_boundaries() -> None:
    assert (
        Request("lmp", date(2026, 3, 8), "TH_NP15_GEN-APND").bounds[1]
        - Request("lmp", date(2026, 3, 8), "TH_NP15_GEN-APND").bounds[0]
    ).total_seconds() == 23 * 3600
    assert (
        Request("lmp", date(2025, 11, 2), "TH_NP15_GEN-APND").bounds[1]
        - Request("lmp", date(2025, 11, 2), "TH_NP15_GEN-APND").bounds[0]
    ).total_seconds() == 25 * 3600
