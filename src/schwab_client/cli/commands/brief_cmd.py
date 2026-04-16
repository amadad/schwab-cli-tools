"""Portfolio brief commands."""

from __future__ import annotations

import sqlite3

from src.core.brief_service import BriefService
from src.core.errors import ConfigError, PortfolioError
from src.schwab_client.runtime_env import load_bash_secrets

from ..output import handle_cli_error, print_json_response

BRIEF_COMMAND_ERRORS = (
    ConfigError,
    PortfolioError,
    OSError,
    sqlite3.Error,
    RuntimeError,
    TypeError,
    ValueError,
)


def cmd_brief(
    *,
    action: str,
    output_mode: str = "text",
    reuse_snapshot_id: int | None = None,
    brief_for_date: str | None = None,
    dry_run: bool = False,
    force: bool = False,
    run_id: int | None = None,
    limit: int = 10,
) -> None:
    command = "brief"
    load_bash_secrets()
    service = BriefService()
    try:
        if action == "nightly":
            result = service.nightly(
                reuse_snapshot_id=reuse_snapshot_id, brief_for_date=brief_for_date
            )
            nightly_data = result.to_dict()
            if output_mode == "json":
                print_json_response(command, data=nightly_data)
            else:
                print(
                    f"READY brief_run_id={nightly_data['brief_run_id']} snapshot_id={nightly_data['snapshot_id']} "
                    f"subject={nightly_data.get('subject') or 'n/a'}"
                )
            return

        if action == "send":
            send_data = service.send(
                run_id=run_id,
                brief_for_date=brief_for_date,
                dry_run=dry_run,
                force=force,
            )
            if output_mode == "json":
                print_json_response(command, data=send_data)
            else:
                print(
                    f"{str(send_data.get('status') or 'unknown').upper()} snapshot_id={send_data.get('snapshot_id')} "
                    f"subject={send_data.get('subject') or send_data.get('reason') or 'n/a'}"
                )
            return

        if action == "status":
            status_data = service.status(limit=limit)
            if output_mode == "json":
                print_json_response(command, data=status_data)
            else:
                print(f"Brief DB: {status_data['db_path']}")
                for run in status_data.get("runs", []):
                    print(
                        f"- #{run['id']} snapshot={run['snapshot_id']} date={run['brief_for_date']} "
                        f"status={run['status']} sent_at={run.get('sent_at') or '—'}"
                    )
            return

        if action == "show":
            brief_run = service.show(run_id or 0)
            if output_mode == "json":
                print_json_response(command, data=brief_run)
            else:
                if not brief_run:
                    print(f"Brief run {run_id} not found.")
                else:
                    print(
                        f"Brief run #{brief_run['id']} snapshot={brief_run['snapshot_id']} status={brief_run['status']}"
                    )
                    print(brief_run.get("email_subject") or "")
                    briefing = brief_run.get("briefing_json") or {}
                    if briefing.get("bottom_line"):
                        print(briefing["bottom_line"])
            return

        raise PortfolioError(f"Unknown brief action: {action}")
    except BRIEF_COMMAND_ERRORS as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)
