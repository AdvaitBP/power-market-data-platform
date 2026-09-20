"""Real adapter/CLI logic with fixture-backed upstream clients and no network."""

import json
import socket
import subprocess
import sys
from collections.abc import Callable
from datetime import date
from unittest.mock import Mock

import gridstatus
import pytest

from power_market_data.cli import main
from power_market_data.domain import TRADING_HUBS
from power_market_data.errors import (
    SchemaError,
    UnsupportedRequestError,
    UpstreamRequestError,
    ValidationError,
)
from power_market_data.sources import caiso

type Rows = Callable[[str], list[dict[str, object]]]
type Frame = Callable[[list[dict[str, object]]], object]


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, rows: Rows, frame: Frame) -> Mock:
    stub = Mock()
    stub.get_lmp.return_value = frame([rows("lmp")[0]])
    stub.get_load.return_value = frame(rows("load"))
    monkeypatch.setattr(gridstatus, "CAISO", lambda: stub)
    return stub


@pytest.mark.parametrize("location", TRADING_HUBS)
def test_lmp_request(
    location: str,
    client: Mock,
    rows: Rows,
    frame: Frame,
) -> None:
    data = [rows("lmp")[0]]
    data[0]["Location"] = location
    client.get_lmp.return_value = frame(data)
    records = caiso.fetch_lmp(date(2026, 8, 1), location)
    assert records[0].location == location
    assert records[0].provenance.source_method == "CAISO.get_lmp"
    assert records[0].provenance.library_version == "0.36.0"
    client.get_lmp.assert_called_once_with(
        date="2026-08-01",
        end="2026-08-02",
        market=gridstatus.Markets.DAY_AHEAD_HOURLY,
        locations=[location],
    )


def test_load_request(client: Mock) -> None:
    records = caiso.fetch_load(date(2026, 8, 1))
    assert len(records) == 2
    assert records[0].provenance.source_url.endswith("/20260801/demand.csv")
    client.get_load.assert_called_once_with(date="2026-08-01")


@pytest.mark.parametrize("product", ["lmp", "load"])
def test_upstream_failure_is_chained(product: str, client: Mock) -> None:
    getattr(client, f"get_{product}").side_effect = TimeoutError("source timeout")
    with pytest.raises(UpstreamRequestError, match="source timeout") as caught:
        if product == "lmp":
            caiso.fetch_lmp(date(2026, 8, 1), TRADING_HUBS[0])
        else:
            caiso.fetch_load(date(2026, 8, 1))
    assert isinstance(caught.value.__cause__, TimeoutError)


def test_upstream_parser_failure(client: Mock) -> None:
    client.get_load.side_effect = KeyError("Current demand")
    with pytest.raises(SchemaError, match="upstream parsing/schema"):
        caiso.fetch_load(date(2026, 8, 1))


def test_unexpected_response_schema(client: Mock) -> None:
    client.get_load.return_value = "upstream HTML"
    with pytest.raises(SchemaError):
        caiso.fetch_load(date(2026, 8, 1))


def test_requested_day_and_location_enforced(client: Mock, rows: Rows, frame: Frame) -> None:
    data = [rows("lmp")[0]]
    data[0]["Location"] = TRADING_HUBS[1]
    client.get_lmp.return_value = frame(data)
    with pytest.raises(ValidationError, match="outside"):
        caiso.fetch_lmp(date(2026, 8, 1), TRADING_HUBS[0])
    with pytest.raises(ValidationError, match="outside"):
        caiso.fetch_load(date(2026, 8, 2))


def test_unsupported_hub_fails_before_network(client: Mock) -> None:
    with pytest.raises(UnsupportedRequestError):
        caiso.fetch_lmp(date(2026, 8, 1), "ALL")
    client.get_lmp.assert_not_called()


def test_future_date_fails_before_network(client: Mock) -> None:
    with pytest.raises(UnsupportedRequestError, match="historical"):
        caiso.fetch_load(date(9999, 1, 1))
    client.get_load.assert_not_called()


def test_fall_back_load_fails_before_network(client: Mock) -> None:
    with pytest.raises(ValidationError, match="fall-back"):
        caiso.fetch_load(date(2025, 11, 2))
    client.get_load.assert_not_called()


@pytest.mark.parametrize("product", ["lmp", "load"])
def test_cli_fixture_success(
    product: str, client: Mock, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["caiso", product, "--date", "2026-08-01", "--limit", "1"]
    if product == "lmp":
        args += ["--location", TRADING_HUBS[0]]
    assert main(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["printed_observations"] == 1
    assert payload["interval_timezone"] == "UTC"
    record = payload["observations"][0]
    assert record["interval_start_utc"].endswith("Z")
    assert len(record["logical_key"]) == len(record["content_hash"]) == 64


def test_cli_failure_nonzero(client: Mock, capsys: pytest.CaptureFixture[str]) -> None:
    client.get_load.side_effect = OSError("offline")
    assert main(["caiso", "load", "--date", "2026-08-01"]) == 1
    captured = capsys.readouterr()
    assert "offline" in captured.err
    assert captured.out == ""


@pytest.mark.parametrize(
    "args",
    [
        ["caiso", "other"],
        ["caiso", "load", "--date", "not-a-date"],
        ["caiso", "load", "--date", "20260801"],
        ["caiso", "load", "--date", "2026-08-01", "--limit", "0"],
        ["caiso", "load", "--date", "2026-08-01", "--limit", "x"],
        ["caiso", "lmp", "--date", "2026-08-01", "--location", "ALL"],
    ],
)
def test_cli_invalid_arguments(args: list[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        main(args)
    assert caught.value.code == 2


def test_module_entrypoint_without_network() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "power_market_data.cli", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "caiso" in result.stdout


def test_unit_network_guard() -> None:
    with pytest.raises(AssertionError, match="forbidden"):
        socket.create_connection(("example.invalid", 443))
