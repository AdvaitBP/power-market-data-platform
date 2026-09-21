"""Planner-backed test state, not a BigQuery transaction or SQL emulator."""

from collections.abc import Sequence
from dataclasses import replace
from datetime import timedelta

from dbt_checks.fixtures import observation
from google.api_core.exceptions import ServiceUnavailable

from power_market_data.domain import Observation
from power_market_data.warehouse.model import (
    CommitUnconfirmed,
    Latest,
    Request,
    Row,
    Snapshot,
    WarehouseError,
    batch_rows,
    plan_write,
)


def records(request: Request) -> list[Observation]:
    original = observation(request.product, "10")
    start = request.bounds[0]
    return [
        replace(
            original,
            interval_start_utc=start,
            interval_end_utc=start
            + timedelta(
                hours=1 if request.product == "lmp" else 0,
                minutes=5 if request.product == "load" else 0,
            ),
        )
    ]


class PlannerState:
    def __init__(self) -> None:
        self.runs: dict[str, Row] = {}
        self.contents: set[str] = set()
        self.latest: dict[str, Latest] = {}
        self.transitions: list[tuple[str, str, int]] = []
        self.sequence = 0
        self.interrupt_day = ""
        self.fail_day = ""
        self.transient_once = False
        self.read_ids: list[str] = []
        self.fetched: list[str] = []

    def get_run(self, run_id: str) -> Row | None:
        self.read_ids.append(run_id)
        if self.transient_once:
            self.transient_once = False
            raise ServiceUnavailable("controlled transient manifest-read failure")  # type: ignore[no-untyped-call]
        return self.runs.get(run_id)

    def begin(self, request: Request, run_id: str) -> None:
        self.runs.setdefault(run_id, {"status": "STARTED", "request_id": request.request_id})

    def reconcile(self, run_id: str) -> Row | None:
        manifest = self.runs[run_id]
        if manifest["status"] == "FAILED":
            raise WarehouseError("terminal FAILED")
        if manifest["status"] == "COMMITTED":
            manifest["status"] = "SUCCEEDED"
        return manifest if manifest["status"] == "SUCCEEDED" else None

    def fetch(self, request: Request) -> Sequence[Observation]:
        self.fetched.append(str(request.day))
        if str(request.day) == self.fail_day:
            raise ValueError("controlled terminal source failure")
        return records(request)

    def fail(self, run_id: str, error: Exception) -> None:
        self.runs[run_id]["status"] = "FAILED"

    def persist(self, request: Request, values: Sequence[Observation], run_id: str) -> Row:
        plan = plan_write(
            run_id,
            batch_rows(request, values),
            Snapshot(self.sequence, frozenset(self.contents), self.latest),
        )
        self.sequence += 1
        for row in plan.contents:
            self.contents.add(str(row["content_id"]))
        for row in plan.transitions:
            key = str(row["logical_key"])
            ordinal = int(str(row["ordinal"]))
            self.latest[key] = Latest(str(row["content_hash"]), ordinal)
            self.transitions.append((key, str(row["content_id"]), ordinal))
        self.runs[run_id].update(
            status="SUCCEEDED",
            rows_accepted=plan.accepted,
            new_contents=len(plan.contents),
            new_transitions=len(plan.transitions),
        )
        if str(request.day) == self.interrupt_day:
            self.interrupt_day = ""
            self.runs[run_id]["status"] = "COMMITTED"
            raise CommitUnconfirmed("controlled loss of acknowledgement")
        return self.runs[run_id]
