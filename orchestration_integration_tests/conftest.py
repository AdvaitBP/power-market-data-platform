import os
from pathlib import Path

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--run-flyte-bigquery", action="store_true", default=False)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if not config.getoption("--run-flyte-bigquery") or os.environ.get("CI"):
        for item in items:
            if Path(__file__).parent not in item.path.parents:
                continue
            item.add_marker(
                pytest.mark.skip(reason="requires --run-flyte-bigquery; never runs in ordinary CI")
            )
