"""Identity is independent of retrieval clocks and Python's randomized hash."""

import json
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal, localcontext

import pytest

from power_market_data.domain import Provenance
from power_market_data.identity import decimal_text, digest
from power_market_data.sources.caiso import normalize_lmp, normalize_load

type Rows = Callable[[str], list[dict[str, object]]]
type Frame = Callable[[list[dict[str, object]]], object]


@pytest.mark.parametrize("product", ["lmp", "load"])
def test_repeated_normalization_and_retrieval_time(
    product: str,
    rows: Rows,
    frame: Frame,
    provenance: Provenance,
) -> None:
    normalize = normalize_lmp if product == "lmp" else normalize_load
    first = normalize(frame(rows(product)), provenance)[0]
    later = replace(provenance, retrieved_at_utc=provenance.retrieved_at_utc + timedelta(days=1))
    second = normalize(frame(rows(product)), later)[0]
    assert first.logical_key == second.logical_key
    assert first.content_hash == second.content_hash
    assert len(first.logical_key) == len(first.content_hash) == 64
    assert first.provenance != second.provenance


@pytest.mark.parametrize(
    ("product", "field"),
    [
        ("lmp", "LMP"),
        ("lmp", "Energy"),
        ("lmp", "Congestion"),
        ("lmp", "Loss"),
        ("load", "Load"),
    ],
)
def test_value_revision_preserves_key_and_changes_content(
    product: str,
    field: str,
    rows: Rows,
    frame: Frame,
    provenance: Provenance,
) -> None:
    normalize = normalize_lmp if product == "lmp" else normalize_load
    data = rows(product)
    first = normalize(frame(data), provenance)[0]
    data[0][field] = Decimal("123.456")
    revised = normalize(frame(data), provenance)[0]
    assert first.logical_key == revised.logical_key
    assert first.content_hash != revised.content_hash


@pytest.mark.parametrize("product", ["lmp", "load"])
def test_interval_changes_key(
    product: str, rows: Rows, frame: Frame, provenance: Provenance
) -> None:
    normalize = normalize_lmp if product == "lmp" else normalize_load
    record = normalize(frame(rows(product)), provenance)[0]
    shifted = replace(
        record,
        interval_start_utc=record.interval_start_utc + timedelta(hours=1),
        interval_end_utc=record.interval_end_utc + timedelta(hours=1),
    )
    assert record.logical_key != shifted.logical_key


def test_location_changes_key(rows: Rows, frame: Frame, provenance: Provenance) -> None:
    first = normalize_lmp(frame(rows("lmp")), provenance)[0]
    assert first.logical_key != replace(first, location="TH_ZP26_GEN-APND").logical_key


def test_canonical_numeric_encoding() -> None:
    assert decimal_text(Decimal("-0.000")) == "0"
    assert decimal_text(Decimal("12.34000")) == "12.34"
    assert decimal_text(Decimal("1.2300E+4")) == "12300"
    with localcontext() as context:
        context.prec = 2
        assert decimal_text(Decimal("123.456")) == "123.456"


def test_numeric_representation_does_not_create_revision(
    rows: Rows,
    frame: Frame,
    provenance: Provenance,
) -> None:
    data = rows("load")
    first = normalize_load(frame(data), provenance)[0]
    data[0]["Load"] = Decimal("21000.0000")
    assert first.content_hash == normalize_load(frame(data), provenance)[0].content_hash


def test_canonical_serialization_across_processes() -> None:
    fields = {"source": "CAISO", "location": "TH_NP15_GEN-APND"}
    expected = digest("observation-key/v1", fields)
    script = (
        "import json; from power_market_data.identity import digest; "
        f"print(digest('observation-key/v1', json.loads({json.dumps(fields)!r})))"
    )
    for seed in ("1", "98765"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        result = subprocess.run(
            [sys.executable, "-c", script],
            env=env,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        assert result.stdout.strip() == expected
    assert digest("observation-key/v1", dict(reversed(list(fields.items())))) == expected
    assert digest("observation-content/v1", fields) != expected
