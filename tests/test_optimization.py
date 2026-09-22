"""Small analytical answers plus independently recomputed physical invariants."""

import math
import random
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from importlib import import_module
from typing import Any

import pytest

from power_market_data.errors import ValidationError
from power_market_data.optimization.battery import solve_battery_dispatch
from power_market_data.optimization.model import (
    BatteryConfig,
    OptimizationError,
    PriceInterval,
    validate_dispatch,
)


def config(**changes: Any) -> BatteryConfig:
    return replace(
        BatteryConfig(
            energy_capacity_mwh=1,
            max_charge_mw=1,
            max_discharge_mw=1,
            charge_efficiency=1,
            discharge_efficiency=1,
            initial_soc_mwh=0,
            terminal_soc_mwh=0,
        ),
        **changes,
    )


def prices(*values: float) -> tuple[PriceInterval, ...]:
    start = datetime(2026, 8, 1, 7, tzinfo=UTC)
    return tuple(
        PriceInterval(
            start + timedelta(hours=i), start + timedelta(hours=i + 1), Decimal(str(value))
        )
        for i, value in enumerate(values)
    )


def test_low_high_hand_calculation() -> None:
    result = solve_battery_dispatch(prices(10, 30), config())
    assert result.charge_mw == pytest.approx((1, 0))
    assert result.discharge_mw == pytest.approx((0, 1))
    assert result.soc_mwh == pytest.approx((0, 1, 0))
    assert result.objective_usd == pytest.approx(20)
    assert result.status == "optimal"
    assert result.solver == "HIGHS"
    assert result.mip_gap == pytest.approx(0)


def test_round_trip_efficiency_hand_calculation() -> None:
    result = solve_battery_dispatch(
        prices(5, 20), config(charge_efficiency=0.9, discharge_efficiency=0.9)
    )
    assert result.charge_mw == pytest.approx((1, 0))
    assert result.discharge_mw == pytest.approx((0, 0.81))
    assert result.soc_mwh == pytest.approx((0, 0.9, 0))
    assert result.objective_usd == pytest.approx(20 * 0.81 - 5)


@pytest.mark.parametrize(
    ("values", "changes"),
    [
        ((50, 50, 50), {"throughput_cost_usd_per_mwh": 1}),
        ((10, 11), {"charge_efficiency": 0.9, "discharge_efficiency": 0.9}),
        ((10, 12), {"throughput_cost_usd_per_mwh": 2}),
    ],
)
def test_flat_or_insufficient_spread_is_idle(
    values: tuple[float, ...], changes: dict[str, float]
) -> None:
    result = solve_battery_dispatch(prices(*values), config(**changes))
    assert result.charge_mw == pytest.approx((0,) * len(values))
    assert result.discharge_mw == pytest.approx((0,) * len(values))
    assert result.objective_usd == pytest.approx(0)


def test_terminal_soc_prevents_free_liquidation() -> None:
    result = solve_battery_dispatch(prices(100), config(initial_soc_mwh=1, terminal_soc_mwh=1))
    assert result.discharge_mw == pytest.approx((0,))
    assert result.soc_mwh == pytest.approx((1, 1))
    assert result.objective_usd == pytest.approx(0)
    # Deliberately incomplete test-only LP: free initial energy can be sold.
    cp = import_module("cvxpy")
    discharge = cp.Variable(nonneg=True)
    loose = cp.Problem(cp.Maximize(100 * discharge), [discharge <= 1])
    loose.solve(solver="HIGHS", threads=1)
    assert loose.value == pytest.approx(100)


def test_negative_price_loose_lp_burns_energy_but_milp_cannot() -> None:
    result = solve_battery_dispatch(
        prices(-100), config(charge_efficiency=0.9, discharge_efficiency=0.9)
    )
    assert result.charge_mw == pytest.approx((0,))
    assert result.discharge_mw == pytest.approx((0,))
    assert result.objective_usd == pytest.approx(0)
    cp = import_module("cvxpy")
    charge, discharge = cp.Variable(nonneg=True), cp.Variable(nonneg=True)
    loose = cp.Problem(
        cp.Maximize(-100 * (discharge - charge)),
        [charge <= 1, discharge <= 1, 0.9 * charge == discharge / 0.9],
    )
    loose.solve(solver="HIGHS", threads=1)
    assert charge.value == pytest.approx(1)
    assert discharge.value == pytest.approx(0.81)
    assert loose.value == pytest.approx(19)


@pytest.mark.parametrize(
    ("changes", "volume"),
    [
        ({"energy_capacity_mwh": 2, "max_charge_mw": 0.5, "max_discharge_mw": 0.5}, 0.5),
        ({"energy_capacity_mwh": 0.4}, 0.4),
    ],
)
def test_power_and_energy_limits(changes: dict[str, float], volume: float) -> None:
    result = solve_battery_dispatch(prices(10, 30), config(**changes))
    assert result.charge_mw == pytest.approx((volume, 0))
    assert result.discharge_mw == pytest.approx((0, volume))
    assert result.objective_usd == pytest.approx(20 * volume)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("energy_capacity_mwh", 0),
        ("energy_capacity_mwh", -1),
        ("energy_capacity_mwh", float("inf")),
        ("energy_capacity_mwh", True),
        ("max_charge_mw", -1),
        ("max_discharge_mw", -1),
        ("charge_efficiency", 0),
        ("discharge_efficiency", 1.01),
        ("initial_soc_mwh", -1),
        ("terminal_soc_mwh", 2),
        ("throughput_cost_usd_per_mwh", -1),
        ("interval_hours", 0.5),
        ("initial_soc_mwh", float("nan")),
    ],
)
def test_invalid_config(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        config(**{field: value})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_prices(value: float) -> None:
    with pytest.raises(ValidationError, match="finite"):
        prices(value)


def test_bad_horizon_and_timestamps() -> None:
    with pytest.raises(ValidationError, match="1 through 25"):
        solve_battery_dispatch((), config())
    with pytest.raises(ValidationError, match="1 through 25"):
        solve_battery_dispatch(prices(*range(26)), config())
    sequence = prices(1, 2, 3)
    for invalid in ((sequence[0], sequence[0]), (sequence[0], sequence[2]), sequence[::-1]):
        with pytest.raises(ValidationError, match="continuous"):
            solve_battery_dispatch(invalid, config())
    with pytest.raises(ValidationError, match="aware UTC"):
        replace(sequence[0], start_utc=sequence[0].start_utc.replace(tzinfo=None))
    with pytest.raises(ValidationError, match="one hour"):
        replace(sequence[0], end_utc=sequence[0].end_utc + timedelta(hours=1))


def test_infeasible_is_visible_not_zero_dispatch() -> None:
    with pytest.raises(OptimizationError, match="infeasible"):
        solve_battery_dispatch(prices(1), config(max_charge_mw=0, terminal_soc_mwh=1))


@pytest.mark.parametrize("seed", range(10))
def test_generated_physical_and_economic_invariants(seed: int) -> None:
    rng = random.Random(seed)
    series = prices(*(rng.uniform(-70, 130) for _ in range(12)))
    settings = config(
        energy_capacity_mwh=2,
        initial_soc_mwh=1,
        terminal_soc_mwh=1,
        charge_efficiency=0.9,
        discharge_efficiency=0.95,
        throughput_cost_usd_per_mwh=0.3,
    )
    result = solve_battery_dispatch(series, settings)
    assert result.soc_mwh[0] == pytest.approx(1)
    assert result.soc_mwh[-1] == pytest.approx(1)
    assert all(-1e-6 <= soc <= 2 + 1e-6 for soc in result.soc_mwh)
    for t, (charge, discharge) in enumerate(
        zip(result.charge_mw, result.discharge_mw, strict=True)
    ):
        assert -1e-6 <= charge <= 1 + 1e-6
        assert -1e-6 <= discharge <= 1 + 1e-6
        assert min(charge, discharge) <= 1e-6
        assert result.soc_mwh[t + 1] == pytest.approx(
            result.soc_mwh[t] + 0.9 * charge - discharge / 0.95, abs=1e-6
        )
    expected = math.fsum(
        float(p.price_usd_per_mwh) * (d - c) - 0.3 * (d + c)
        for p, c, d in zip(series, result.charge_mw, result.discharge_mw, strict=True)
    )
    assert result.objective_usd == pytest.approx(expected, abs=1e-5)
    assert result.objective_usd >= -1e-5  # Idle is feasible for equal boundary SOC.


@pytest.mark.parametrize("corruption", ["length", "soc", "objective", "exclusive", "nonfinite"])
def test_independent_checker_rejects_corruption(corruption: str) -> None:
    series, settings = prices(10, 30), config()
    good = solve_battery_dispatch(series, settings)
    bad = {
        "length": replace(good, soc_mwh=(0, 0)),
        "soc": replace(good, soc_mwh=(0, 2, 0)),
        "objective": replace(good, objective_usd=100),
        "exclusive": replace(good, discharge_mw=(1, 1)),
        "nonfinite": replace(good, charge_mw=(float("nan"), 0)),
    }[corruption]
    with pytest.raises(OptimizationError):
        validate_dispatch(series, settings, bad)


def test_solver_failure_and_time_limit_are_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    cp = import_module("cvxpy")

    def fail(*args: object, **kwargs: object) -> None:
        raise cp.error.SolverError("controlled solver error")

    monkeypatch.setattr(cp.Problem, "solve", fail)
    with pytest.raises(OptimizationError, match="solver failure"):
        solve_battery_dispatch(prices(1), config())
    with pytest.raises(ValidationError, match="time limit"):
        solve_battery_dispatch(prices(1), config(), time_limit_seconds=0)
