"""Local JSON reports and one optional daily figure; cloud reads are explicit."""

import argparse
import json
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from importlib.metadata import version
from pathlib import Path
from typing import cast

from power_market_data.backtesting.engine import backtest_daily
from power_market_data.backtesting.inputs import from_row, requests
from power_market_data.backtesting.warehouse import read_prices
from power_market_data.domain import TRADING_HUBS
from power_market_data.errors import ValidationError
from power_market_data.optimization.model import BatteryConfig


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--start-date", type=date.fromisoformat, required=True)
    parser.add_argument(
        "--end-date",
        type=date.fromisoformat,
        required=True,
        help="Inclusive Pacific market date; at most 7 days",
    )
    parser.add_argument("--location", choices=TRADING_HUBS, required=True)
    parser.add_argument("--config", type=Path, required=True, help="Explicit battery JSON config")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input-json", type=Path, help="Offline array of input-mart-shaped rows")
    source.add_argument("--warehouse", action="store_true", help="Read the existing dbt input mart")
    parser.add_argument(
        "--output", type=Path, help="Optional local JSON report; never cloud output"
    )
    parser.add_argument(
        "--figure", type=Path, help="Optional HTML figure for the first selected day"
    )


def encode(value: object) -> str:
    if isinstance(value, (date, datetime, Decimal)):
        return str(value)
    raise TypeError(f"cannot serialize {type(value).__name__}")


def run(args: argparse.Namespace) -> None:
    requests(args.start_date, args.end_date, args.location)
    try:
        settings = json.loads(args.config.read_text(encoding="utf-8"))
        if not isinstance(settings, dict):
            raise ValidationError("battery config must be a JSON object")
        config = BatteryConfig(**settings)
        usage = None
        if args.input_json is not None:
            data = json.loads(args.input_json.read_text(encoding="utf-8"))
            if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
                raise ValidationError("input JSON must contain an array of mart rows")
            inputs = tuple(from_row(row) for row in cast(list[dict[str, object]], data))
            input_kind = "offline file; source authenticity is not independently verified"
        else:
            inputs, usage = read_prices(args.start_date, args.end_date, args.location)
            input_kind = "live current analytical mart"
        result = backtest_daily(inputs, args.start_date, args.end_date, args.location, config)
        payload = {
            "input_kind": input_kind,
            "versions": {
                name: version(name) for name in ("power-market-data-platform", "cvxpy", "highspy")
            },
            "query_usage": asdict(usage) if usage else None,
            "backtest": asdict(result),
        }
        report = json.dumps(payload, default=encode, indent=2, allow_nan=False)
        if args.output is not None:
            args.output.write_text(report + "\n", encoding="utf-8")
        if args.figure is not None:
            from power_market_data.backtesting.figure import write_daily_figure

            write_daily_figure(result.days[0], args.figure, input_kind)
        print(report)
    except (OSError, ValueError, TypeError) as exc:
        raise ValidationError(f"battery backtest input/output error: {exc}") from exc
