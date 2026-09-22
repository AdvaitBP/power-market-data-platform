"""Credential-free mart-to-MILP/metrics/CLI integration, including Pacific DST."""

import json
import subprocess
import sys
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from power_market_data.backtesting.engine import backtest_daily
from power_market_data.backtesting.inputs import from_row, requests
from power_market_data.backtesting.warehouse import read_prices
from power_market_data.cli import main
from power_market_data.errors import PowerMarketDataError, ValidationError
from power_market_data.optimization.model import BatteryConfig

ROOT = Path(__file__).resolve().parents[1]
HUB = "TH_NP15_GEN-APND"
DAY = date(2026, 8, 1)


def settings() -> BatteryConfig:
    return BatteryConfig(**json.loads((ROOT / "examples/battery_reference.json").read_text()))


def rows_for(day: date = DAY) -> list[dict[str, Any]]:
    template = json.loads((ROOT / "tests/fixtures/battery_prices.json").read_text())[0]
    first, stop = requests(day, day, HUB)[0].bounds
    count = int((stop - first).total_seconds() / 3600)
    result = []
    for i in range(count):
        row = dict(
            template,
            market_date=str(day),
            interval_start_utc=(first + timedelta(hours=i)).isoformat(),
            interval_end_utc=(first + timedelta(hours=i + 1)).isoformat(),
            lmp=str(10 if i < count // 2 else 70),
            logical_key=f"synthetic-key-{day}-{i}",
            content_id=f"synthetic-content-{day}-{i}",
        )
        result.append(row)
    return result


def test_daily_metrics_and_boundaries() -> None:
    rows = tuple(from_row(row) for row in rows_for())
    result = backtest_daily(rows, DAY, DAY, HUB, settings())
    day = result.days[0]
    assert day.interval_count == 24
    # 2 MWh of empty cell capacity -> 2/.95 grid MWh charged; 2*.95 discharged.
    assert day.metrics.charged_mwh == pytest.approx(2 / 0.95)
    assert day.metrics.discharged_mwh == pytest.approx(2 * 0.95)
    assert day.metrics.cell_throughput_mwh == pytest.approx(4)
    assert day.metrics.equivalent_full_cycles == pytest.approx(0.5)
    assert day.dispatch.gross_arbitrage_value_usd == pytest.approx(70 * 1.9 - 10 * 2 / 0.95)
    assert day.metrics.initial_soc_mwh == day.metrics.terminal_soc_mwh == pytest.approx(2)
    assert day.metrics.minimum_soc_mwh == pytest.approx(2)
    assert day.metrics.maximum_soc_mwh == pytest.approx(4)
    assert day.inputs == rows
    assert result.aggregate.total_gross_arbitrage_value_usd == pytest.approx(
        day.dispatch.gross_arbitrage_value_usd
    )


@pytest.mark.parametrize(
    ("day", "hours"),
    [
        (date(2025, 3, 9), 23),
        (date(2025, 11, 2), 25),
        (date(2025, 1, 15), 24),
        (date(2025, 7, 15), 24),
    ],
)
def test_pacific_days_keep_utc_continuity(day: date, hours: int) -> None:
    rows = tuple(from_row(row) for row in rows_for(day))
    result = backtest_daily(rows, day, day, HUB, settings())
    assert result.days[0].interval_count == hours
    assert result.days[0].dispatch.soc_mwh[-1] == pytest.approx(2)
    assert len({row.interval.start_utc for row in rows}) == hours


def test_aggregate_is_daily_independent_and_interval_weighted() -> None:
    start, end = date(2025, 3, 8), date(2025, 3, 9)
    rows = tuple(from_row(row) for day in (start, end) for row in rows_for(day))
    result = backtest_daily(rows, start, end, HUB, settings())
    assert [day.interval_count for day in result.days] == [24, 23]
    assert result.aggregate.grid_throughput_mwh == pytest.approx(
        sum(day.metrics.grid_throughput_mwh for day in result.days)
    )
    assert result.aggregate.equivalent_full_cycles == pytest.approx(1)
    assert result.aggregate.average_daily_gross_value_usd == pytest.approx(
        result.aggregate.total_gross_arbitrage_value_usd / 2
    )
    assert result.aggregate.median_daily_gross_value_usd == pytest.approx(
        result.aggregate.average_daily_gross_value_usd
    )
    assert result.aggregate.charging_percent == pytest.approx(
        100 * sum(day.metrics.charging_intervals for day in result.days) / 47
    )
    assert (
        result.aggregate.charging_percent
        + result.aggregate.discharging_percent
        + result.aggregate.idle_percent
    ) == pytest.approx(100)
    for day in result.days:
        assert day.dispatch.soc_mwh[0] == day.dispatch.soc_mwh[-1] == pytest.approx(2)


@pytest.mark.parametrize(
    "broken", ["missing", "duplicate_key", "duplicate_hour", "outside", "boundary"]
)
def test_bad_daily_coverage_rejected_before_solve(
    broken: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [from_row(row) for row in rows_for()]
    if broken == "missing":
        rows.pop()
    elif broken == "duplicate_key":
        rows[1] = replace(rows[1], logical_key=rows[0].logical_key)
    elif broken == "duplicate_hour":
        rows[1] = replace(rows[1], interval=rows[0].interval)
    elif broken == "outside":
        rows[1] = replace(rows[1], location="TH_SP15_GEN-APND")
    elif broken == "boundary":
        rows = [from_row(row) for row in rows_for(DAY + timedelta(days=1))]
    solver = Mock(side_effect=AssertionError("solver must not run"))
    monkeypatch.setattr("power_market_data.backtesting.engine.solve_battery_dispatch", solver)
    with pytest.raises(ValidationError):
        backtest_daily(rows, DAY, DAY, HUB, settings())
    solver.assert_not_called()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source", "other"),
        ("unit", "MW"),
        ("market", "REAL_TIME_5_MIN"),
        ("logical_key_schema", "v2"),
        ("content_hash_schema", "v2"),
        ("lmp", None),
        ("lmp", "NaN"),
        ("lmp", 10.1),
        ("logical_key", ""),
        ("state_ordinal", True),
        ("commit_sequence", 0),
        ("market_date", "2026-08-02"),
        ("state_known_at", "2026-09-01T00:00:00"),
        ("interval_start_utc", "2026-08-01T07:00:00"),
    ],
)
def test_input_contract_rejects_malformed_fields(field: str, value: object) -> None:
    row = rows_for()[0]
    row[field] = value
    with pytest.raises(ValidationError):
        from_row(row)


def test_missing_column_and_invalid_range() -> None:
    row = rows_for()[0]
    del row["lmp"]
    with pytest.raises(ValidationError, match="missing"):
        from_row(row)
    for start, end, hub in (
        (DAY, DAY - timedelta(days=1), HUB),
        (DAY, DAY + timedelta(days=7), HUB),
        (DAY, DAY, "unknown"),
        (date(2100, 1, 1), date(2100, 1, 1), HUB),
    ):
        with pytest.raises(PowerMarketDataError):
            requests(start, end, hub)
    with pytest.raises(ValidationError, match="equal"):
        backtest_daily([], DAY, DAY, HUB, replace(settings(), terminal_soc_mwh=0))


def test_warehouse_query_is_bounded_capped_and_preserves_lineage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GCP_PROJECT_ID", "offline-project")
    monkeypatch.setenv("BQ_ANALYTICS_DATASET", "test_analytics")
    job = SimpleNamespace(
        result=Mock(return_value=rows_for()),
        job_id="synthetic-query",
        total_bytes_processed=123,
        total_bytes_billed=456,
    )
    client = SimpleNamespace(query=Mock(return_value=job))
    rows, usage = read_prices(DAY, DAY, HUB, client=client)
    (sql,) = client.query.call_args.args
    kwargs = client.query.call_args.kwargs
    config = kwargs["job_config"]
    assert "test_analytics.mart_battery_optimization_inputs" in sql
    assert "BETWEEN @start AND @end AND location = @hub" in sql
    assert "contents" not in sql
    assert config.maximum_bytes_billed == 104857600
    assert [(p.name, p.value) for p in config.query_parameters] == [
        ("start", DAY),
        ("end", DAY),
        ("hub", HUB),
    ]
    assert kwargs["job_retry"] is None
    assert len(rows) == 24
    assert usage.bytes_billed == 456
    assert rows[0].content_id == rows_for()[0]["content_id"]
    monkeypatch.setenv("BQ_ANALYTICS_DATASET", "unsafe`name")
    with pytest.raises(ValidationError):
        read_prices(DAY, DAY, HUB, client=client)
    assert client.query.call_count == 1


def test_cli_offline_report_and_figure(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output, figure = tmp_path / "report.json", tmp_path / "dispatch.html"
    args = [
        "battery-backtest",
        "--start-date",
        str(DAY),
        "--end-date",
        str(DAY),
        "--location",
        HUB,
        "--config",
        str(ROOT / "examples/battery_reference.json"),
        "--input-json",
        str(ROOT / "tests/fixtures/battery_prices.json"),
        "--output",
        str(output),
        "--figure",
        str(figure),
    ]
    assert main(args) == 0
    report = json.loads(output.read_text())
    assert report["query_usage"] is None
    assert "offline" in report["input_kind"]
    assert report["backtest"]["days"][0]["dispatch"]["status"] == "optimal"
    assert len(report["backtest"]["days"][0]["inputs"]) == 24
    assert "Perfect-foresight daily benchmark" in figure.read_text(encoding="utf-8")
    assert "Boundary SOC (MWh)" in figure.read_text(encoding="utf-8")
    assert json.loads(capsys.readouterr().out) == report
    args[args.index("--config") + 1] = str(tmp_path / "missing.json")
    assert main(args) == 1
    assert "input/output error" in capsys.readouterr().err


def test_base_import_does_not_load_solver() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import power_market_data.cli; import sys; assert 'cvxpy' not in sys.modules",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
