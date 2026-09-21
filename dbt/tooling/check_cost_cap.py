"""Offline regression check in the isolated dbt environment; no client/network I/O."""

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, main
from unittest.mock import Mock, patch

import yaml
from dbt.adapters.bigquery.connections import BigQueryConnectionManager
from dbt.adapters.bigquery.credentials import BigQueryCredentials


class CostCapTest(TestCase):
    def test_adapter_forwards_profile_cap_to_native_client(self) -> None:
        profile = yaml.safe_load(
            (Path(__file__).resolve().parents[1] / "profiles.example.yml").read_text("utf-8")
        )["power_market_analytics"]["outputs"]["dev"]
        cap = profile["maximum_bytes_billed"]
        self.assertEqual(cap, 104857600)
        client = Mock()
        client.query.return_value = SimpleNamespace(
            location=None,
            job_id="offline-cap-test",
            project=None,
            result=Mock(return_value=[]),
        )
        conn = SimpleNamespace(
            name="offline",
            handle=client,
            credentials=BigQueryCredentials.from_dict(
                {
                    "method": "oauth",
                    "database": "offline-project",
                    "schema": "analytics",
                    "maximum_bytes_billed": cap,
                }
            ),
        )
        manager = Mock()
        manager.get_thread_connection.return_value = conn
        manager.get_labels_from_query_comment.return_value = {}
        manager.exception_handler.return_value = nullcontext()
        manager.generate_job_id.return_value = "offline-cap-test"
        manager._retry.create_reopen_with_deadline.return_value = lambda call: call
        manager._retry.create_job_execution_timeout.return_value = 120
        manager._retry.create_job_creation_timeout.return_value = 120
        manager._query_and_results.side_effect = lambda *a, **kw: (
            BigQueryConnectionManager._query_and_results(manager, *a, **kw)
        )
        manager._submit_or_attach.side_effect = lambda client, job_id, submit: submit()
        module = "dbt.adapters.bigquery.connections"
        with (
            patch(module + ".fire_event"),
            patch(module + ".get_node_info", return_value={}),
            patch(module + ".get_invocation_id", return_value="offline"),
        ):
            BigQueryConnectionManager.raw_execute(manager, "select 1")
        configuration = client.query.call_args.kwargs["job_config"].to_api_repr()
        self.assertEqual(configuration["query"]["maximumBytesBilled"], str(cap))
        client.query.assert_called_once()


if __name__ == "__main__":
    main()
