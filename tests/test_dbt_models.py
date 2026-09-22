"""Execute the portable SELECT logic, not an emulation of BigQuery MERGE/types.

dbt parse validates the full project separately. Credentialed integration tests
exercise native materialization, NUMERIC/TIMESTAMP and dbt's own data/unit tests.
"""

import json
import sqlite3
from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from dbt_checks.fixtures import FACTS, STEPS, scenario
from jinja2 import Environment, StrictUndefined

from power_market_data.warehouse.model import Row
from power_market_data.warehouse.schema import TABLES

ROOT = Path(__file__).resolve().parents[1]
MODELS = {path.stem: path for path in (ROOT / "dbt" / "models").rglob("*.sql")}


def sql(name: str, incremental: bool = False) -> str:
    template = Environment(undefined=StrictUndefined).from_string(
        MODELS.get(name, ROOT / "dbt/tests" / f"{name}.sql").read_text(encoding="utf-8")
    )
    return template.render(
        ref=lambda name: name,
        source=lambda _, name: "raw_" + name,
        is_incremental=lambda: incremental,
        this=name,
    )


def scalar(value: object) -> str | int | None:
    if value is None or isinstance(value, (int, str)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(type(value))


def load_raw(connection: sqlite3.Connection, tables: dict[str, list[Row]]) -> None:
    for name, rows in tables.items():
        fields = TABLES[name]
        connection.execute(f"delete from raw_{name}")
        placeholders = ", ".join("?" for _ in fields)
        connection.executemany(
            f"insert into raw_{name} values ({placeholders})",
            [tuple(scalar(row.get(field)) for field, _, _ in fields) for row in rows],
        )


@pytest.fixture
def database() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    for name, fields in TABLES.items():
        columns = ", ".join(
            f"{field} {'INTEGER' if kind in ('INT64', 'BOOL') else 'TEXT'}"
            for field, kind, _ in fields
        )
        connection.execute(f"create table raw_{name} ({columns})")
    for name in (
        "stg_ingestion_runs",
        "stg_lmp_contents",
        "stg_load_contents",
        "stg_lmp_state_transitions",
        "stg_load_state_transitions",
        "int_lmp_revision_history",
        "int_load_revision_history",
        "mart_ingestion_health",
    ):
        connection.execute(f"create view {name} as {sql(name)}")
    try:
        yield connection
    finally:
        connection.close()


@pytest.mark.parametrize("product", FACTS)
def test_incremental_revisions_and_full_refresh(
    database: sqlite3.Connection,
    product: str,
) -> None:
    fact = FACTS[product]
    previous: dict[str, dict[str, object]] = {}
    original_first_seen: object = None
    for index, step in enumerate(STEPS):
        load_raw(database, scenario(step))
        expected = [dict(row) for row in database.execute(sql(fact))]
        if index == 0:
            database.execute(f"create table {fact} as {sql(fact)}")
            original_first_seen = expected[0]["first_seen_at"]
            candidates = expected
        else:
            candidates = [dict(row) for row in database.execute(sql(fact, True))]
        assert len(candidates) == (0 if step == "repeat" else 1)
        for row in candidates:
            previous[str(row["logical_key"])] = row
        # Compare query candidates plus prior state with an independently
        # evaluated full-refresh SELECT; this does not test dbt's MERGE engine.
        assert previous == {str(row["logical_key"]): row for row in expected}
        assert len(expected) == (2 if step == "late" else 1)
        if step in ("initial", "repeat", "reappearance"):
            assert expected[0][product] == "10"
            assert expected[0]["first_seen_at"] == original_first_seen
        if step == "revision":
            assert expected[0][product] == "20"
        if step == "reappearance":
            assert expected[0]["state_ordinal"] == 3
            assert expected[0]["state_known_at"] > original_first_seen
        if step == "late":
            old = next(row for row in expected if str(row["market_date"]).startswith("2025"))
            assert str(old["state_known_at"]).startswith("2026")
        # The previous fact is fixture state for the NEXT SELECT, not a fake MERGE.
        database.execute(f"drop table {fact}")
        database.execute(f"create table {fact} as {sql(fact)}")


@pytest.mark.parametrize("product", FACTS)
def test_history_and_ineligible_runs(database: sqlite3.Connection, product: str) -> None:
    load_raw(database, scenario("reappearance"))
    contents = database.execute(f"select * from stg_{product}_contents").fetchall()
    history = database.execute(
        f"select * from int_{product}_revision_history order by state_ordinal"
    ).fetchall()
    assert len(contents) == 2
    assert len(history) == 3
    assert [row[product] for row in history] == ["10", "20", "10"]
    assert history[0]["content_id"] == history[2]["content_id"]
    assert history[0]["first_seen_at"] == history[2]["first_seen_at"]
    assert history[0]["state_known_at"] < history[2]["state_known_at"]
    health = database.execute(
        "select * from mart_ingestion_health where product = ?", (product,)
    ).fetchone()
    assert health["succeeded_run_count"] == 4
    assert health["failed_run_count"] == 1
    assert health["unfinalized_run_count"] == 1
    assert health["started_run_count"] == 1


@pytest.mark.parametrize("product", FACTS)
def test_current_uses_ordinal_before_clock(database: sqlite3.Connection, product: str) -> None:
    tables = scenario("reappearance", ineligible=False)
    transitions = tables[f"{product}_state_transitions"]
    transitions[0]["known_at"] = datetime(2030, 1, 1)
    load_raw(database, tables)
    current = database.execute(sql(FACTS[product])).fetchone()
    assert current["state_ordinal"] == 3
    assert current["transition_id"] == transitions[-1]["transition_id"]


@pytest.mark.parametrize("product", FACTS)
def test_missing_successful_content_is_not_invented(
    database: sqlite3.Connection,
    product: str,
) -> None:
    tables = scenario("initial", ineligible=False)
    tables[f"{product}_contents"] = []
    load_raw(database, tables)
    assert not database.execute(sql(FACTS[product])).fetchall()
    # Native reconciliation compares directly with raw transitions and fails
    # this missing history/current row; the view does not synthesize a value.


def test_fixture_is_small_and_obviously_synthetic() -> None:
    tables = scenario("late")
    assert len(json.dumps(tables, default=str)) < 50000
    assert all(
        "example.invalid" in str(row["source_url"])
        for name in ("lmp_contents", "load_contents")
        for row in tables[name]
    )


@pytest.mark.parametrize(
    ("raw", "target", "custom"),
    [
        ("power_market_raw", "power_market_raw", None),
        ("custom_raw", "custom_raw", None),
        ("custom_raw", "power_market_raw", "audit"),
        ("analytics_audit", "analytics", "audit"),
    ],
)
def test_schema_guard_rejects_raw_outputs(raw: str, target: str, custom: str | None) -> None:
    from types import SimpleNamespace

    def reject(message: str) -> None:
        raise ValueError(message)

    template = Environment(undefined=StrictUndefined).from_string(
        (ROOT / "dbt/macros/guard_analytics_schema.sql").read_text("utf-8")
    )
    module = template.make_module(
        {
            "env_var": lambda name, default: raw,
            "target": SimpleNamespace(schema=target),
            "exceptions": SimpleNamespace(raise_compiler_error=reject),
        }
    )
    with pytest.raises(ValueError, match="Analytics target must differ"):
        module.__dict__["generate_schema_name"](custom, None)


@pytest.mark.parametrize("product", FACTS)
@pytest.mark.parametrize("broken", ("current_transition", "current_clock", "missing_history"))
def test_reconciliation_surfaces_corruption(
    database: sqlite3.Connection,
    product: str,
    broken: str,
) -> None:
    tables = scenario("reappearance")
    load_raw(database, tables)
    fact = FACTS[product]
    database.execute(f"create table {fact} as {sql(fact)}")
    check = sql("reconcile_" + product)
    assert not database.execute(check).fetchall()
    if broken == "current_transition":
        database.execute(f"update {fact} set transition_id = 'unknown'")
    elif broken == "current_clock":
        database.execute(f"update {fact} set state_known_at = NULL")
    else:
        # Remove the historical B content, while the current A still exists.
        database.execute(f"delete from raw_{product}_contents where {product} = '20'")
    errors = database.execute(check).fetchall()
    assert errors
    assert {row["contract"] for row in errors} == (
        {"history"} if broken == "missing_history" else {"current"}
    )


@pytest.mark.parametrize("step", STEPS)
def test_battery_inputs_preserve_only_current_eligible_state(
    database: sqlite3.Connection, step: str
) -> None:
    load_raw(database, scenario(step))
    database.execute(f"create view fct_hourly_lmp as {sql('fct_hourly_lmp')}")
    inputs = [dict(row) for row in database.execute(sql("mart_battery_optimization_inputs"))]
    facts = [dict(row) for row in database.execute("select * from fct_hourly_lmp")]
    assert len(inputs) == len(facts) == (2 if step == "late" else 1)
    assert inputs == [{key: fact[key] for key in inputs[0]} for fact in facts]
    if step == "reappearance":
        assert inputs[0]["lmp"] == "10"
        assert inputs[0]["state_ordinal"] == 3
