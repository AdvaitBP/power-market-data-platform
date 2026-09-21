"""Run the SDK, not undecorated Python functions. No cloud or source credentials."""

import os
import subprocess
import sys
from pathlib import Path

import flyte
import pytest

from orchestration_checks.fixture_workflow import verify_workflow

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("mode", ["cli", "sdk"])
def test_native_fixture_graph(mode: str) -> None:
    if mode == "sdk":
        run = flyte.with_runcontext(
            mode="local", raw_data_path=str(ROOT / "artifacts/flyte-checks/raw")
        ).run(verify_workflow, product="load")
        run.wait()
        assert str(run.outputs()[0]).startswith("PASS:")
        return
    binary = Path(sys.executable).parent / ("flyte.exe" if os.name == "nt" else "flyte")
    result = subprocess.run(
        [
            str(binary),
            "run",
            "--local",
            "--raw-data-path",
            str(ROOT / "artifacts/flyte-checks/raw"),
            "orchestration_checks/fixture_workflow.py",
            "verify_workflow",
        ],
        cwd=ROOT,
        env={
            **os.environ,
            "PYTHONUTF8": "1",
            "GOOGLE_APPLICATION_CREDENTIALS": "deliberately-missing-credentials.json",
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    log = ROOT / "artifacts/phase4-local-workflow.log"
    log.parent.mkdir(exist_ok=True)
    log.write_text(result.stdout + result.stderr, encoding="utf-8")
    assert result.returncode == 0, f"native Flyte CLI failed; see {log}"
    assert "PASS:" in result.stdout


@pytest.mark.parametrize("mode", ["cli", "sdk"])
def test_invalid_typed_plan_rejected_before_credentials(mode: str) -> None:
    import json
    from dataclasses import asdict

    from flyte.errors import RuntimeUserError
    from orchestration.flyte_pipeline import backfill
    from orchestration.plan import Backfill

    spec = Backfill("00000000000000000000000000000001", "2026-08-04", "2026-08-02")
    if mode == "sdk":
        with pytest.raises(RuntimeUserError, match="1 through 7"):
            run = flyte.with_runcontext(mode="local").run(backfill, spec=spec)
            run.wait()
        return
    binary = Path(sys.executable).parent / ("flyte.exe" if os.name == "nt" else "flyte")
    result = subprocess.run(
        [
            str(binary),
            "run",
            "--local",
            "orchestration/flyte_pipeline.py",
            "backfill",
            "--spec",
            json.dumps(asdict(spec)),
        ],
        cwd=ROOT,
        env={
            **os.environ,
            "PYTHONUTF8": "1",
            "GOOGLE_APPLICATION_CREDENTIALS": "deliberately-missing-credentials.json",
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    assert result.returncode != 0
    assert "1 through 7" in result.stdout + result.stderr
