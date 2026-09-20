"""Synthetic source-shape fixtures and an offline-only test boundary."""

import json
import socket
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn, cast

import pandas as pd  # type: ignore[import-untyped]  # Used only to reproduce upstream frames.
import pytest

from power_market_data.domain import Provenance


@pytest.fixture(autouse=True)
def block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("network access is forbidden in unit tests")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)


@pytest.fixture
def rows() -> Callable[[str], list[dict[str, object]]]:
    def load(product: str) -> list[dict[str, object]]:
        path = Path(__file__).parent / "fixtures" / f"caiso_{product}.json"
        result = cast(list[dict[str, object]], json.loads(path.read_text(encoding="utf-8")))
        for row in result:
            for key in ("Time", "Interval Start", "Interval End"):
                row[key] = pd.Timestamp(row[key]).tz_convert("US/Pacific")
        return result

    return load


@pytest.fixture
def frame() -> Callable[[list[dict[str, object]]], object]:
    return lambda rows: cast(object, pd.DataFrame(rows))


@pytest.fixture
def provenance() -> Provenance:
    return Provenance(
        retrieved_at_utc=datetime(2026, 9, 1, tzinfo=UTC),
        source_url="https://example.invalid/synthetic",
        source_method="fixture",
        library_version="0.36.0",
    )
