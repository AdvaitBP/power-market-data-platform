"""UTC identity across Pacific winter, summer and DST transitions."""

from collections.abc import Callable
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from power_market_data.domain import Provenance
from power_market_data.errors import ValidationError
from power_market_data.sources.caiso import normalize_lmp, normalize_load
from power_market_data.time import as_utc

PACIFIC = ZoneInfo("America/Los_Angeles")


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (datetime(2026, 1, 15, 12, tzinfo=UTC), datetime(2026, 1, 15, 12, tzinfo=UTC)),
        (datetime(2026, 1, 15, 12, tzinfo=PACIFIC), datetime(2026, 1, 15, 20, tzinfo=UTC)),
        (datetime(2026, 7, 15, 12, tzinfo=PACIFIC), datetime(2026, 7, 15, 19, tzinfo=UTC)),
        (datetime(2026, 3, 8, 1, tzinfo=PACIFIC), datetime(2026, 3, 8, 9, tzinfo=UTC)),
        (datetime(2026, 3, 8, 3, tzinfo=PACIFIC), datetime(2026, 3, 8, 10, tzinfo=UTC)),
        (datetime(2025, 11, 2, 1, fold=0, tzinfo=PACIFIC), datetime(2025, 11, 2, 8, tzinfo=UTC)),
        (datetime(2025, 11, 2, 1, fold=1, tzinfo=PACIFIC), datetime(2025, 11, 2, 9, tzinfo=UTC)),
    ],
)
def test_explicit_conversions(source: datetime, expected: datetime) -> None:
    result = as_utc(source)
    assert result == expected
    assert result.tzinfo is UTC


@pytest.mark.parametrize(
    "source",
    [
        datetime(2025, 11, 2, 1, 30),
        datetime(2026, 3, 8, 2, 30),
        datetime(2026, 1, 1),
        datetime(2026, 3, 8, 2, 30, tzinfo=PACIFIC),
    ],
)
def test_naive_or_nonexistent_time_rejected(source: datetime) -> None:
    with pytest.raises(ValidationError):
        as_utc(source)


def test_fall_back_lmp_intervals_have_distinct_keys(
    rows: Callable[[str], list[dict[str, object]]],
    frame: Callable[[list[dict[str, object]]], object],
    provenance: Provenance,
) -> None:
    template = rows("lmp")[0]
    data = []
    for start, end in [
        ("2025-11-02T01:00:00-07:00", "2025-11-02T01:00:00-08:00"),
        ("2025-11-02T01:00:00-08:00", "2025-11-02T02:00:00-08:00"),
    ]:
        data.append(
            {
                **template,
                "Time": datetime.fromisoformat(start),
                "Interval Start": datetime.fromisoformat(start),
                "Interval End": datetime.fromisoformat(end),
            }
        )
    records = normalize_lmp(frame(data), provenance)
    assert records[0].logical_key != records[1].logical_key
    assert records[0].interval_end_utc == records[1].interval_start_utc


def test_spring_forward_lmp_interval(
    rows: Callable[[str], list[dict[str, object]]],
    frame: Callable[[list[dict[str, object]]], object],
    provenance: Provenance,
) -> None:
    row = rows("lmp")[0]
    row.update(
        {
            "Time": datetime(2026, 3, 8, 1, tzinfo=PACIFIC),
            "Interval Start": datetime(2026, 3, 8, 1, tzinfo=PACIFIC),
            "Interval End": datetime(2026, 3, 8, 3, tzinfo=PACIFIC),
        }
    )
    record = normalize_lmp(frame([row]), provenance)[0]
    assert record.interval_start_utc.hour == 9
    assert record.interval_end_utc.hour == 10


def test_guessed_fall_back_load_is_rejected(
    rows: Callable[[str], list[dict[str, object]]],
    frame: Callable[[list[dict[str, object]]], object],
    provenance: Provenance,
) -> None:
    row = rows("load")[0]
    row.update(
        {
            "Time": datetime(2025, 11, 2, 1, tzinfo=PACIFIC),
            "Interval Start": datetime(2025, 11, 2, 1, tzinfo=PACIFIC),
            "Interval End": datetime(2025, 11, 2, 1, 5, tzinfo=PACIFIC),
        }
    )
    with pytest.raises(ValidationError, match="fall-back"):
        normalize_load(frame([row]), provenance)


def test_spring_forward_load_interval(
    rows: Callable[[str], list[dict[str, object]]],
    frame: Callable[[list[dict[str, object]]], object],
    provenance: Provenance,
) -> None:
    row = rows("load")[0]
    row.update(
        {
            "Time": datetime(2026, 3, 8, 1, 55, tzinfo=PACIFIC),
            "Interval Start": datetime(2026, 3, 8, 1, 55, tzinfo=PACIFIC),
            "Interval End": datetime(2026, 3, 8, 3, tzinfo=PACIFIC),
        }
    )
    record = normalize_load(frame([row]), provenance)[0]
    assert record.interval_start_utc == datetime(2026, 3, 8, 9, 55, tzinfo=UTC)
    assert record.interval_end_utc == datetime(2026, 3, 8, 10, tzinfo=UTC)
