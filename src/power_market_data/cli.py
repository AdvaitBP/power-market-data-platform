"""Inspect bounded CAISO data or persist it to an explicitly configured raw warehouse."""

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import date

from google.api_core.exceptions import GoogleAPICallError

from power_market_data.domain import TRADING_HUBS, Observation, observation_dict
from power_market_data.errors import PowerMarketDataError
from power_market_data.ingestion import ingest
from power_market_data.sources.caiso import fetch_lmp, fetch_load
from power_market_data.warehouse.bigquery import BigQueryWarehouse, new_run_id
from power_market_data.warehouse.model import Request, WarehouseConfig, WarehouseError


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


def _products(parser: argparse.ArgumentParser, persist: bool = False) -> None:
    products = parser.add_subparsers(dest="product", required=True)
    for product in ("lmp", "load"):
        command = products.add_parser(product)
        command.add_argument("--date", type=_date, required=True, help="Pacific calendar date")
        if persist:
            command.add_argument("--run-id", help="Resume a previously printed run ID")
        else:
            command.add_argument("--limit", type=_limit, default=5, help="Rows to print, not fetch")
        if product == "lmp":
            command.add_argument("--location", choices=TRADING_HUBS, required=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    _products(commands.add_parser("caiso", help="Print CAISO historical observations"))
    ingestion = commands.add_parser("ingest", help="Fetch and persist one historical day")
    sources = ingestion.add_subparsers(dest="source", required=True)
    _products(sources.add_parser("caiso"), persist=True)
    warehouse = commands.add_parser("warehouse", help="Explicit BigQuery management")
    operations = warehouse.add_subparsers(dest="operation", required=True)
    operations.add_parser("bootstrap", help="Create/check raw schema without replacing data")
    resume = operations.add_parser("resume", help="Reconcile a submitted commit, without fetching")
    resume.add_argument("--run-id", required=True)
    _products(operations.add_parser("inspect", help="Bounded counts and run manifests"))
    from power_market_data.backtesting.cli import configure, run

    configure(
        commands.add_parser("battery-backtest", help="Daily perfect-foresight battery benchmark")
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "battery-backtest":
            run(args)
            return 0
        if args.command in ("warehouse", "ingest"):
            store = BigQueryWarehouse(WarehouseConfig.from_environment())
            if args.command == "warehouse" and args.operation == "bootstrap":
                store.bootstrap()
                payload: object = {
                    "dataset": f"{store.config.project}.{store.config.dataset}",
                    "status": "schema checked",
                }
            elif args.command == "warehouse" and args.operation == "resume":
                payload = store.reconcile(args.run_id)
                if payload is None:
                    raise WarehouseError("no commit submitted; rerun ingest with this run ID")
            else:
                request = Request(args.product, args.date, getattr(args, "location", None))
                if args.command == "ingest":
                    run_id = args.run_id or new_run_id()
                    print(f"run_id={run_id}", file=sys.stderr, flush=True)
                    payload = ingest(store, request, run_id)
                else:
                    payload = store.inspect(request, args.limit)
            print(json.dumps(payload, default=str, indent=2))
            return 0
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
    except GoogleAPICallError as exc:
        print(
            f"error: BigQuery {type(exc).__name__}; check configuration and job diagnostics",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
