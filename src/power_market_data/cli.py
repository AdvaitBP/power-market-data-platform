"""Bounded live inspection; prints observations and never writes fetched data."""

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import date

from power_market_data.domain import TRADING_HUBS, Observation, observation_dict
from power_market_data.errors import PowerMarketDataError
from power_market_data.sources.caiso import fetch_lmp, fetch_load


def _date(text: str) -> date:
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must be YYYY-MM-DD") from exc
    if parsed.isoformat() != text:
        raise argparse.ArgumentTypeError("date must be YYYY-MM-DD")
    return parsed


def _limit(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("limit must be a positive integer") from exc
    if value < 1:
        raise argparse.ArgumentTypeError("limit must be a positive integer")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sources = parser.add_subparsers(dest="source", required=True)
    caiso = sources.add_parser("caiso", help="Inspect CAISO historical observations")
    products = caiso.add_subparsers(dest="product", required=True)
    for product in ("lmp", "load"):
        command = products.add_parser(product)
        command.add_argument("--date", type=_date, required=True, help="Pacific calendar date")
        command.add_argument("--limit", type=_limit, default=5, help="Rows to print, not fetch")
        if product == "lmp":
            command.add_argument("--location", choices=TRADING_HUBS, required=True)
    args = parser.parse_args(argv)
    try:
        records: Sequence[Observation]
        if args.product == "lmp":
            records = fetch_lmp(args.date, args.location)
        else:
            records = fetch_load(args.date)
        print(
            json.dumps(
                {
                    "source": "CAISO",
                    "product": args.product,
                    "requested_date_pacific": str(args.date),
                    "fetched_observations": len(records),
                    "printed_observations": min(args.limit, len(records)),
                    "interval_timezone": "UTC",
                    "observations": [observation_dict(record) for record in records[: args.limit]],
                },
                indent=2,
            )
        )
        return 0
    except PowerMarketDataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
