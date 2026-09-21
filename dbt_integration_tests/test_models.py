"""One controlled end-to-end contract, covering both products and real dbt MERGE."""

from decimal import Decimal

from dbt_checks.fixtures import FACTS, STEPS

from dbt_integration_tests.conftest import DbtWarehouse


def test_revision_incremental_and_full_refresh(warehouse: DbtWarehouse) -> None:
    original_content: dict[str, str] = {}
    original_clock: dict[str, object] = {}
    for index, step in enumerate(STEPS):
        warehouse.publish(step)
        if index == 0:
            warehouse.dbt("build")
        else:
            warehouse.dbt("run", "--select", *FACTS.values())
        for product, fact in FACTS.items():
            rows = warehouse.rows(fact)
            assert len(rows) == (2 if step == "late" else 1)
            current = next(row for row in rows if row["market_date"].year == 2026)
            assert current[product] == Decimal("20" if step == "revision" else "10")
            if index == 0:
                original_content[product] = current["content_id"]
                original_clock[product] = current["first_seen_at"]
            if step == "reappearance":
                assert current["content_id"] == original_content[product]
                assert current["first_seen_at"] == original_clock[product]
                assert current["state_ordinal"] == 3
                assert current["state_known_at"] > current["first_seen_at"]
            if step == "late":
                late = next(row for row in rows if row["market_date"].year == 2025)
                assert late["state_known_at"].year == 2026
            prefix = f"{warehouse.raw.project}.{warehouse.analytics}"
            contents_table = f"{prefix}.stg_{product}_contents"
            history_table = f"{prefix}.int_{product}_revision_history"
            counts = warehouse.query(f"""
                select
                  (select count(*) from `{contents_table}`) as contents,
                  (select count(*) from `{history_table}`) as transitions,
                  array(select as struct h.*, r.status as originating_status
                        from `{history_table}` as h
                        join `{warehouse.raw.table("ingestion_runs")}` as r
                          on h.state_run_id = r.run_id
                        order by h.logical_key, h.state_ordinal) as history
            """)
            assert counts[0]["contents"] == (1, 1, 2, 2, 3)[index]
            assert counts[0]["transitions"] == (1, 1, 2, 3, 4)[index]
            history = counts[0]["history"]
            assert len(history) == counts[0]["transitions"]
            assert {row["originating_status"] for row in history} == {"SUCCEEDED"}
            assert all(
                row["transition_id"] in {h["transition_id"] for h in history} for row in rows
            )
            if step == "reappearance":
                assert [row[product] for row in history] == [
                    Decimal("10"),
                    Decimal("20"),
                    Decimal("10"),
                ]
                assert history[0]["content_id"] == history[2]["content_id"]
                assert history[0]["first_seen_at"] == history[2]["first_seen_at"]
                assert history[0]["state_known_at"] < history[2]["state_known_at"]
            warehouse.report.setdefault("observed_states", {}).setdefault(step, {})[product] = {
                "contents": counts[0]["contents"],
                "transitions": counts[0]["transitions"],
                "history": history,
                "facts": rows,
            }
        warehouse.report.setdefault("scenarios_passed", []).append(step)

    before = {
        name: sorted(warehouse.rows(name), key=lambda row: row["logical_key"])
        for name in FACTS.values()
    }
    warehouse.dbt("build", "--full-refresh")
    after = {
        name: sorted(warehouse.rows(name), key=lambda row: row["logical_key"])
        for name in FACTS.values()
    }
    assert before == after
    warehouse.report["full_refresh_equal"] = True
    warehouse.report["incremental_facts"] = before
    warehouse.report["full_refresh_facts"] = after

    # BigQuery date/DST semantics, using constants rather than a public data scan.
    result = warehouse.query("""
        select d, timestamp_diff(
          timestamp(date_add(d, interval 1 day), 'America/Los_Angeles'),
          timestamp(d, 'America/Los_Angeles'), hour) as hours
        from unnest([date '2026-03-08', date '2026-11-01']) as d order by d
    """)
    assert [row["hours"] for row in result] == [23, 25]

    # In this disposable dataset only, duplicate a fact and require the native
    # uniqueness data test to report FAIL (an infrastructure error is insufficient).
    table = f"{warehouse.raw.project}.{warehouse.analytics}.fct_hourly_lmp"
    warehouse.query(f"insert into `{table}` select * from `{table}` limit 1")
    warehouse.dbt("test", "--select", "unique_fct_hourly_lmp_logical_key", expected_failure=True)
    warehouse.dbt("run", "--full-refresh", "--select", *FACTS.values())
    warehouse.dbt("test", "--select", "unique_fct_hourly_lmp_logical_key")
    warehouse.dbt("docs", "generate")
    warehouse.report["contract_failure_surfaced"] = True
