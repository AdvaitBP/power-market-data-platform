"""Units and numerical contracts for a bounded hourly battery horizon."""

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from power_market_data.errors import PowerMarketDataError, ValidationError

PHYSICAL_TOLERANCE = 1e-6
OBJECTIVE_TOLERANCE = 1e-5


class OptimizationError(PowerMarketDataError):
    """A solver or independently checked dispatch failed its contract."""


def finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValidationError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValidationError(f"{name} must be a finite number")
    return result


@dataclass(frozen=True, kw_only=True)
class BatteryConfig:
    energy_capacity_mwh: float
    max_charge_mw: float
    max_discharge_mw: float
    charge_efficiency: float
    discharge_efficiency: float
    initial_soc_mwh: float
    terminal_soc_mwh: float
    throughput_cost_usd_per_mwh: float = 0.0
    interval_hours: float = 1.0

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            finite(getattr(self, name), name)
        if self.energy_capacity_mwh <= 0:
            raise ValidationError("energy capacity must be positive MWh")
        if min(self.max_charge_mw, self.max_discharge_mw) < 0:
            raise ValidationError("power limits must be nonnegative MW")
        if not all(0 < value <= 1 for value in (self.charge_efficiency, self.discharge_efficiency)):
            raise ValidationError("efficiencies must be in (0, 1]")
        if not all(
            0 <= value <= self.energy_capacity_mwh
            for value in (self.initial_soc_mwh, self.terminal_soc_mwh)
        ):
            raise ValidationError("initial and terminal SOC must be inside energy capacity")
        if self.throughput_cost_usd_per_mwh < 0:
            raise ValidationError("throughput cost must be nonnegative")
        if self.interval_hours != 1:
            raise ValidationError("only one-hour intervals are supported")


@dataclass(frozen=True)
class PriceInterval:
    start_utc: datetime
    end_utc: datetime
    price_usd_per_mwh: Decimal

    def __post_init__(self) -> None:
        for timestamp in (self.start_utc, self.end_utc):
            if not isinstance(timestamp, datetime) or timestamp.tzinfo is None:
                raise ValidationError("price interval timestamps must be aware UTC")
            if timestamp.utcoffset() != timedelta(0):
                raise ValidationError("price interval timestamps must be UTC")
            if timestamp.minute or timestamp.second or timestamp.microsecond:
                raise ValidationError("price intervals must start/end on an hourly boundary")
        if self.end_utc - self.start_utc != timedelta(hours=1):
            raise ValidationError("price interval must last exactly one hour")
        finite(self.price_usd_per_mwh, "price")
        if not isinstance(self.price_usd_per_mwh, Decimal):
            raise ValidationError("price must be Decimal, preserving input precision")
        object.__setattr__(self, "start_utc", self.start_utc.astimezone(UTC))
        object.__setattr__(self, "end_utc", self.end_utc.astimezone(UTC))


@dataclass(frozen=True)
class DispatchResult:
    solver: str
    status: str
    objective_usd: float
    gross_arbitrage_value_usd: float
    throughput_cost_usd: float
    solve_seconds: float | None
    mip_gap: float | None
    mip_node_count: int | None
    charge_mw: tuple[float, ...]
    discharge_mw: tuple[float, ...]
    soc_mwh: tuple[float, ...]
    charging_mode: tuple[int, ...]


def validate_dispatch(
    prices: tuple[PriceInterval, ...], config: BatteryConfig, result: DispatchResult
) -> None:
    """Reconcile the returned solution without CVXPY expressions or solver residuals."""
    n = len(prices)
    if (
        len(result.charge_mw),
        len(result.discharge_mw),
        len(result.soc_mwh),
        len(result.charging_mode),
    ) != (n, n, n + 1, n):
        raise OptimizationError("dispatch vector lengths do not match the horizon")
    values = (
        *result.charge_mw,
        *result.discharge_mw,
        *result.soc_mwh,
        result.objective_usd,
        result.gross_arbitrage_value_usd,
        result.throughput_cost_usd,
    )
    if not all(math.isfinite(value) for value in values):
        raise OptimizationError("dispatch contains nonfinite values")
    tol = PHYSICAL_TOLERANCE
    if any(value < -tol or value > config.energy_capacity_mwh + tol for value in result.soc_mwh):
        raise OptimizationError("SOC violates energy bounds")
    if (
        abs(result.soc_mwh[0] - config.initial_soc_mwh) > tol
        or abs(result.soc_mwh[-1] - config.terminal_soc_mwh) > tol
    ):
        raise OptimizationError("dispatch violates initial/terminal SOC")
    for t, (charge, discharge, mode) in enumerate(
        zip(result.charge_mw, result.discharge_mw, result.charging_mode, strict=True)
    ):
        if mode not in (0, 1):
            raise OptimizationError("operating mode must be binary")
        if (
            charge < -tol
            or discharge < -tol
            or charge > config.max_charge_mw * mode + tol
            or discharge > config.max_discharge_mw * (1 - mode) + tol
        ):
            raise OptimizationError("dispatch violates power/exclusivity bounds")
        expected = (
            result.soc_mwh[t]
            + config.charge_efficiency * charge * config.interval_hours
            - discharge * config.interval_hours / config.discharge_efficiency
        )
        if abs(expected - result.soc_mwh[t + 1]) > tol:
            raise OptimizationError("SOC transition does not reconcile")
    gross = math.fsum(
        float(p.price_usd_per_mwh) * (d - c) * config.interval_hours
        for p, c, d in zip(prices, result.charge_mw, result.discharge_mw, strict=True)
    )
    cost = (
        math.fsum((*result.charge_mw, *result.discharge_mw))
        * config.interval_hours
        * config.throughput_cost_usd_per_mwh
    )
    for actual, expected in (
        (result.gross_arbitrage_value_usd, gross),
        (result.throughput_cost_usd, cost),
        (result.objective_usd, gross - cost),
    ):
        if not math.isclose(actual, expected, rel_tol=1e-8, abs_tol=OBJECTIVE_TOLERANCE):
            raise OptimizationError("dispatch objective does not reconcile")
