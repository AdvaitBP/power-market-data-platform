"""A small, explicit MILP; no source, warehouse or orchestration dependencies."""

import math
from collections.abc import Sequence
from importlib import import_module

from power_market_data.errors import ValidationError
from power_market_data.optimization.model import (
    PHYSICAL_TOLERANCE,
    BatteryConfig,
    DispatchResult,
    OptimizationError,
    PriceInterval,
    finite,
    validate_dispatch,
)


def solve_battery_dispatch(
    prices: Sequence[PriceInterval], config: BatteryConfig, *, time_limit_seconds: float = 30
) -> DispatchResult:
    intervals = tuple(prices)
    if not 1 <= len(intervals) <= 25:
        raise ValidationError("optimizer horizon must contain 1 through 25 hourly intervals")
    if any(
        left.end_utc != right.start_utc
        for left, right in zip(intervals, intervals[1:], strict=False)
    ):
        raise ValidationError("optimizer intervals must be sorted, unique and continuous")
    limit = finite(time_limit_seconds, "solver time limit")
    if not 0 < limit <= 60:
        raise ValidationError("solver time limit must be in (0, 60] seconds")
    try:
        cp = import_module("cvxpy")
    except ImportError as exc:
        raise OptimizationError("install the optimization extra to use CVXPY/HiGHS") from exc
    if "HIGHS" not in cp.installed_solvers():
        raise OptimizationError("HiGHS is not installed; install the optimization extra")
    n = len(intervals)
    charge = cp.Variable(n, nonneg=True, name="grid_charge_mw")
    discharge = cp.Variable(n, nonneg=True, name="grid_discharge_mw")
    soc = cp.Variable(n + 1, name="soc_mwh")
    mode = cp.Variable(n, boolean=True, name="charging_mode")
    dt = config.interval_hours
    constraints = [
        soc >= 0,
        soc <= config.energy_capacity_mwh,
        charge <= config.max_charge_mw * mode,
        discharge <= config.max_discharge_mw * (1 - mode),
        soc[0] == config.initial_soc_mwh,
        soc[-1] == config.terminal_soc_mwh,
        soc[1:]
        == soc[:-1]
        + config.charge_efficiency * charge * dt
        - discharge * dt / config.discharge_efficiency,
    ]
    price_vector = [float(interval.price_usd_per_mwh) for interval in intervals]
    cash_flow = cp.sum(cp.multiply(price_vector, discharge - charge)) * dt
    cost = config.throughput_cost_usd_per_mwh * cp.sum(charge + discharge) * dt
    problem = cp.Problem(cp.Maximize(cash_flow - cost), constraints)
    try:
        problem.solve(
            solver="HIGHS",
            time_limit=limit,
            threads=1,
            mip_rel_gap=1e-8,
            mip_abs_gap=1e-6,
            mip_feasibility_tolerance=1e-7,
        )
    except cp.error.SolverError as exc:
        raise OptimizationError(f"HiGHS solver failure: {exc}") from exc
    if problem.status != "optimal":
        raise OptimizationError(f"HiGHS returned {problem.status}; no dispatch accepted")
    if any(variable.value is None for variable in (charge, discharge, soc, mode)):
        raise OptimizationError("optimal solution lacks dispatch vectors")
    charge_values = tuple(float(v) for v in charge.value)
    discharge_values = tuple(float(v) for v in discharge.value)
    mode_values = tuple(float(v) for v in mode.value)
    if any(not math.isfinite(v) or abs(v - round(v)) > PHYSICAL_TOLERANCE for v in mode_values):
        raise OptimizationError("solver returned a nonintegral operating mode")
    gross = math.fsum(
        p * (d - c) * dt
        for p, c, d in zip(price_vector, charge_values, discharge_values, strict=True)
    )
    throughput_cost = (
        math.fsum((*charge_values, *discharge_values)) * dt * (config.throughput_cost_usd_per_mwh)
    )
    stats = problem.solver_stats
    info = stats.extra_stats
    gap = getattr(info, "mip_gap", None)
    nodes = getattr(info, "mip_node_count", None)
    result = DispatchResult(
        solver="HIGHS",
        status=str(problem.status),
        objective_usd=float(problem.value),
        gross_arbitrage_value_usd=gross,
        throughput_cost_usd=throughput_cost,
        solve_seconds=float(stats.solve_time) if stats.solve_time is not None else None,
        mip_gap=float(gap) if gap is not None else None,
        mip_node_count=int(nodes) if nodes is not None else None,
        charge_mw=charge_values,
        discharge_mw=discharge_values,
        soc_mwh=tuple(float(v) for v in soc.value),
        charging_mode=tuple(round(v) for v in mode_values),
    )
    validate_dispatch(intervals, config, result)
    return result
