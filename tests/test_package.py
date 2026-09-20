"""Exercise the installed package independently of the repository working directory."""

import subprocess
import sys
from importlib.metadata import version
from pathlib import Path


def test_installed_package_imports_outside_checkout(tmp_path: Path) -> None:
    """An isolated interpreter must find the installed src-layout package."""
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import power_market_data; print(power_market_data.__version__)",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )

    assert result.stdout.strip() == version("power-market-data-platform")
    assert result.stderr == ""
