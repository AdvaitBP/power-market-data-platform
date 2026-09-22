"""Independent daily horizons, with input lineage and recomputed descriptive metrics."""

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from power_market_data.backtesting.inputs import MarketPrice, requests
from power_market_data.errors import ValidationError
from power_market_data.optimization.battery import solve_battery_dispatch
from power_market_data.optimization.model import PHYSICAL_TOLERANCE, BatteryConfig, DispatchResult


@dataclass(frozen=True)
class DayMetrics:
    charged_mwh: float
    discharged_mwh: float
    grid_throughput_mwh: float
    cell_throughput_mwh: float
    equivalent_full_cycles: float
    initial_soc_mwh: float
    terminal_soc_mwh: float
    minimum_soc_mwh: float
    maximum_soc_mwh: float
    charging_intervals: int
    discharging_intervals: int
    idle_intervals: int


@dataclass(frozen=True)
class DayResult:
    market_date: date
    location: str
    interval_count: int
    minimum_price_usd_per_mwh: str
    maximum_price_usd_per_mwh: str
    inputs: tuple[MarketPrice, ...]
    dispatch: DispatchResult
    metrics: DayMetrics


@dataclass(frozen=True)
class Aggregate:
    total_gross_arbitrage_value_usd: float
    average_daily_gross_value_usd: float
    median_daily_gross_value_usd: float
    best_day: date
    worst_day: date
    total_objective_usd: float
    total_throughput_cost_usd: float
    grid_throughput_mwh: float
    cell_throughput_mwh: float
    equivalent_full_cycles: float
    charging_percent: float
    discharging_percent: float
    idle_percent: float


@dataclass(frozen=True)
class BacktestResult:
    config: BatteryConfig
    days: tuple[DayResult, ...]
    aggregate: Aggregate
    input_semantics: str = "current accepted CAISO DAY_AHEAD_HOURLY USD/MWh; perfect foresight"
    result_schema: str = "daily-battery-benchmark/v1"
    logical_key_schema: str = "observation-key/v1"
    content_hash_schema: str = "observation-content/v1"


def backtest_daily(
    inputs: Sequence[MarketPrice], start: date, end: date, location: str, config: BatteryConfig
) -> BacktestResult:
    plan = requests(start, end, location)
    if config.initial_soc_mwh != config.terminal_soc_mwh:
        raise ValidationError("daily benchmark requires equal initial and terminal SOC")
    if any(row.location != location or not start <= row.market_date <= end for row in inputs):
        raise ValidationError("input lies outside the requested dates/hub")
    if len({row.logical_key for row in inputs}) != len(inputs):
        raise ValidationError("duplicate logical key in optimization input")
    # Validate EVERY day before any solve, including 23/25-hour Pacific DST days.
    groups: list[tuple[MarketPrice, ...]] = []
    for request in plan:
        rows = tuple(
            sorted(
                (row for row in inputs if row.market_date == request.day),
                key=lambda row: row.interval.start_utc,
            )
        )
        first, stop = request.bounds
        count = int((stop - first).total_seconds() / 3600)
        if len(rows) != count or any(
            row.interval.start_utc != first + timedelta(hours=i)
            or row.interval.end_utc != first + timedelta(hours=i + 1)
            for i, row in enumerate(rows)
        ):
            raise ValidationError(f"{request.day}: expected {count} continuous hourly intervals")
        groups.append(rows)
    days: list[DayResult] = []
    for rows in groups:
        result = solve_battery_dispatch(tuple(row.interval for row in rows), config)
        charged = math.fsum(result.charge_mw) * config.interval_hours
        discharged = math.fsum(result.discharge_mw) * config.interval_hours
        cell = charged * config.charge_efficiency + discharged / config.discharge_efficiency
        charging = sum(value > PHYSICAL_TOLERANCE for value in result.charge_mw)
        discharging = sum(value > PHYSICAL_TOLERANCE for value in result.discharge_mw)
        metrics = DayMetrics(
            charged,
            discharged,
            charged + discharged,
            cell,
            cell / (2 * config.energy_capacity_mwh),
            result.soc_mwh[0],
            result.soc_mwh[-1],
            min(result.soc_mwh),
            max(result.soc_mwh),
            charging,
            discharging,
            len(rows) - charging - discharging,
        )
        prices = [row.interval.price_usd_per_mwh for row in rows]
        days.append(
            DayResult(
                rows[0].market_date,
                location,
                len(rows),
                str(min(prices)),
                str(max(prices)),
                rows,
                result,
                metrics,
            )
        )
    values = [day.dispatch.gross_arbitrage_value_usd for day in days]
    count = sum(day.interval_count for day in days)
    aggregate = Aggregate(
        math.fsum(values),
        statistics.mean(values),
        statistics.median(values),
        max(days, key=lambda d: d.dispatch.gross_arbitrage_value_usd).market_date,
        min(days, key=lambda d: d.dispatch.gross_arbitrage_value_usd).market_date,
        math.fsum(day.dispatch.objective_usd for day in days),
        math.fsum(day.dispatch.throughput_cost_usd for day in days),
        math.fsum(day.metrics.grid_throughput_mwh for day in days),
        math.fsum(day.metrics.cell_throughput_mwh for day in days),
        math.fsum(day.metrics.equivalent_full_cycles for day in days),
        100 * sum(day.metrics.charging_intervals for day in days) / count,
        100 * sum(day.metrics.discharging_intervals for day in days) / count,
        100 * sum(day.metrics.idle_intervals for day in days) / count,
    )
    return BacktestResult(config, tuple(days), aggregate)
