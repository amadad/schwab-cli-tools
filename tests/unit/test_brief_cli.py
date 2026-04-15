from unittest.mock import patch


@patch("src.schwab_client.cli.cmd_brief")
def test_brief_nightly_routes_to_command(mock_cmd_brief):
    from src.schwab_client.cli import main

    main(["brief", "nightly", "--reuse-snapshot-id", "12", "--json"])

    mock_cmd_brief.assert_called_once_with(
        action="nightly",
        output_mode="json",
        reuse_snapshot_id=12,
        brief_for_date=None,
        dry_run=False,
        force=False,
        run_id=None,
        limit=10,
    )


@patch("src.schwab_client.cli.cmd_brief")
def test_brief_send_routes_force_and_dry_run(mock_cmd_brief):
    from src.schwab_client.cli import main

    main(["brief", "send", "--run-id", "5", "--dry-run", "--force"])

    mock_cmd_brief.assert_called_once_with(
        action="send",
        output_mode="text",
        reuse_snapshot_id=None,
        brief_for_date=None,
        dry_run=True,
        force=True,
        run_id=5,
        limit=10,
    )
