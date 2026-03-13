"""Tests for snapshot/report command behavior."""

from pathlib import Path
from unittest.mock import patch

from src.schwab_client.cli.commands.report import cmd_snapshot


@patch("src.schwab_client.cli.commands.report.print_json_response")
@patch("src.schwab_client.cli.commands.report._write_snapshot_artifact")
@patch("src.schwab_client.cli.commands.report._capture_snapshot")
def test_cmd_snapshot_output_flag_without_value_uses_default_path(
    mock_capture_snapshot,
    mock_write_snapshot_artifact,
    mock_print_json_response,
):
    snapshot = {
        "generated_at": "2026-03-13T12:00:00",
        "portfolio": {"summary": {"total_value": 100.0, "total_cash": 10.0}},
        "market": None,
        "history": {"snapshot_id": 123, "db_path": "/tmp/history.db"},
    }
    mock_capture_snapshot.return_value = snapshot
    mock_write_snapshot_artifact.return_value = Path("/tmp/report.json")

    cmd_snapshot(output_mode="json", output_path="", include_market=False)

    mock_capture_snapshot.assert_called_once_with(include_market=False, source_command="snapshot")
    mock_write_snapshot_artifact.assert_called_once_with(snapshot, "")
    mock_print_json_response.assert_called_once_with(
        "snapshot",
        data={
            "snapshot": snapshot,
            "output_path": "/tmp/report.json",
        },
    )
