"""Source contracts, including values that must never be silently repaired."""

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

import pandas as pd  # type: ignore[import-untyped]
import pytest

from power_market_data.domain import Provenance, observation_dict
from power_market_data.errors import SchemaError, UpstreamRequestError, ValidationError
from power_market_data.sources.caiso import normalize_lmp, normalize_load

type Rows = Callable[[str], list[dict[str, object]]]
type Frame = Callable[[list[dict[str, object]]], object]


def test_lmp_source_shape(rows: Rows, frame: Frame, provenance: Provenance) -> None:
    records = normalize_lmp(frame(rows("lmp")), provenance)
    assert [r.location for r in records] == ["TH_NP15_GEN-APND", "TH_SP15_GEN-APND"]
    first = records[0]
    assert first.source == "CAISO"
    assert first.market == "DAY_AHEAD_HOURLY"
    assert first.unit == "USD/MWh"
    assert first.interval_start_utc == datetime(2026, 8, 1, 7, tzinfo=UTC)
    assert first.interval_end_utc == datetime(2026, 8, 1, 8, tzinfo=UTC)
    assert type(first.interval_start_utc) is datetime
    assert (first.lmp, first.energy, first.congestion, first.loss) == (
        Decimal("45.25"),
        Decimal("42"),
        Decimal("0.75"),
        Decimal("2.5"),
    )
    assert records[1].lmp == Decimal("-7")
    assert first.provenance is provenance
    assert observation_dict(first)["interval_start_pacific"] == "2026-08-01T00:00:00-07:00"


@pytest.mark.parametrize(
    "column",
    [
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
    ],
)
def test_missing_lmp_column(column: str, rows: Rows, frame: Frame, provenance: Provenance) -> None:
    data = rows("lmp")
    for row in data:
        del row[column]
    with pytest.raises(SchemaError, match="missing required columns"):
        normalize_lmp(frame(data), provenance)


@pytest.mark.parametrize(
    "column",
    [
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
    ],
)
def test_missing_lmp_value(column: str, rows: Rows, frame: Frame, provenance: Provenance) -> None:
    data = rows("lmp")
    data[0][column] = None
    with pytest.raises(ValidationError):
        normalize_lmp(frame(data), provenance)


@pytest.mark.parametrize("value", [True, "45.2", float("nan"), float("inf"), float("-inf")])
def test_invalid_price(value: object, rows: Rows, frame: Frame, provenance: Provenance) -> None:
    data = rows("lmp")
    data[0]["LMP"] = value
    with pytest.raises(ValidationError, match="LMP"):
        normalize_lmp(frame(data), provenance)


def test_prices_have_no_arbitrary_cap_or_component_sum_rule(
    rows: Rows,
    frame: Frame,
    provenance: Provenance,
) -> None:
    data = rows("lmp")
    data[0]["LMP"] = 1_000_000
    assert normalize_lmp(frame(data), provenance)[0].lmp == Decimal("1000000")


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("Market", "REAL_TIME_5_MIN"),
        ("Location", "UNKNOWN"),
        ("Location Type", "Node"),
        ("Interval End", datetime(2026, 8, 1, 7, tzinfo=UTC)),
        ("Interval End", datetime(2026, 8, 1, 6, tzinfo=UTC)),
        ("Interval End", datetime(2026, 8, 1, 9, tzinfo=UTC)),
        ("Time", datetime(2026, 8, 1, 8, tzinfo=UTC)),
        ("Interval Start", datetime(2026, 8, 1)),
    ],
)
def test_invalid_lmp_contract(
    column: str,
    value: object,
    rows: Rows,
    frame: Frame,
    provenance: Provenance,
) -> None:
    data = rows("lmp")
    data[0][column] = value
    with pytest.raises(ValidationError):
        normalize_lmp(frame(data), provenance)


def test_load_source_shape(rows: Rows, frame: Frame, provenance: Provenance) -> None:
    records = normalize_load(frame(rows("load")), provenance)
    assert records[0].unit == "MW"
    assert records[0].area == "CAISO"
    assert records[0].load == Decimal("21000")
    assert records[1].load == Decimal("21234.5")
    assert records[0].interval_start_utc == datetime(2026, 8, 1, 7, tzinfo=UTC)
    assert records[0].interval_end_utc == datetime(2026, 8, 1, 7, 5, tzinfo=UTC)
    assert type(records[0].interval_start_utc) is datetime


@pytest.mark.parametrize("column", ["Time", "Interval Start", "Interval End", "Load"])
def test_missing_load_value(column: str, rows: Rows, frame: Frame, provenance: Provenance) -> None:
    data = rows("load")
    data[0][column] = None
    with pytest.raises(ValidationError):
        normalize_load(frame(data), provenance)


@pytest.mark.parametrize("value", [-1, "21000", True, float("inf"), float("nan")])
def test_invalid_load(value: object, rows: Rows, frame: Frame, provenance: Provenance) -> None:
    data = rows("load")
    data[0]["Load"] = value
    with pytest.raises(ValidationError):
        normalize_load(frame(data), provenance)


def test_zero_load_allowed(rows: Rows, frame: Frame, provenance: Provenance) -> None:
    data = rows("load")
    data[0]["Load"] = 0
    assert normalize_load(frame(data), provenance)[0].load == 0


def test_missing_load_column(rows: Rows, frame: Frame, provenance: Provenance) -> None:
    data = rows("load")
    for row in data:
        del row["Load"]
    with pytest.raises(SchemaError, match="Load"):
        normalize_load(frame(data), provenance)


@pytest.mark.parametrize("product", ["lmp", "load"])
def test_duplicate_observation_is_visible(
    product: str,
    rows: Rows,
    frame: Frame,
    provenance: Provenance,
) -> None:
    data = rows(product)
    data.append(data[0].copy())
    normalize = normalize_lmp if product == "lmp" else normalize_load
    with pytest.raises(ValidationError, match="duplicate logical"):
        normalize(frame(data), provenance)


@pytest.mark.parametrize("malformed", [None, [], {}, 123, "unexpected HTML"])
def test_malformed_frame(malformed: object, provenance: Provenance) -> None:
    with pytest.raises(SchemaError):
        normalize_load(malformed, provenance)


def test_empty_response_has_no_success_semantics(provenance: Provenance) -> None:
    class EmptyFrame:
        columns = ["Time", "Interval Start", "Interval End", "Load"]

        def to_dict(self, orient: str) -> object:
            return []

    with pytest.raises(UpstreamRequestError, match="no observations"):
        normalize_load(EmptyFrame(), provenance)


def test_duplicate_columns_rejected(provenance: Provenance) -> None:
    class BadFrame:
        columns = ["Time", "Time", "Interval Start", "Interval End", "Load"]

        def to_dict(self, orient: str) -> object:
            return []

    with pytest.raises(SchemaError, match="duplicate columns"):
        normalize_load(BadFrame(), provenance)


def test_nullable_identifier_is_validation_error(
    rows: Rows,
    frame: Frame,
    provenance: Provenance,
) -> None:
    # A pandas nullable sentinel must not escape as an ambiguous-boolean TypeError.
    data = rows("lmp")
    data[0]["Market"] = pd.NA
    with pytest.raises(ValidationError, match="expected DAY_AHEAD"):
        normalize_lmp(frame(data), provenance)


@pytest.mark.parametrize(
    "end",
    [
        datetime(2026, 8, 1, 7, tzinfo=UTC),
        datetime(2026, 8, 1, 7, 10, tzinfo=UTC),
    ],
)
def test_invalid_load_duration(
    end: datetime,
    rows: Rows,
    frame: Frame,
    provenance: Provenance,
) -> None:
    data = rows("load")
    data[0]["Interval End"] = end
    with pytest.raises(ValidationError, match="interval"):
        normalize_load(frame(data), provenance)


def test_submicrosecond_timestamp_rejected(
    rows: Rows,
    frame: Frame,
    provenance: Provenance,
) -> None:
    data = rows("lmp")
    data[0]["Interval Start"] = pd.Timestamp("2026-08-01T07:00:00.000000001Z")
    with pytest.raises(ValidationError, match="sub-microsecond"):
        normalize_lmp(frame(data), provenance)


def test_bad_dataframe_conversion_is_schema_error(provenance: Provenance) -> None:
    class BadFrame:
        columns = ["Time", "Interval Start", "Interval End", "Load"]

        def to_dict(self, orient: str) -> object:
            raise ValueError("cannot convert source rows")

    with pytest.raises(SchemaError, match="conversion"):
        normalize_load(BadFrame(), provenance)
