"""Portfolio brief commands."""

from __future__ import annotations

from src.core.brief_service import BriefService
from src.core.errors import PortfolioError
from src.schwab_client.runtime_env import load_bash_secrets

from ..output import handle_cli_error, print_json_response


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
            result = service.nightly(reuse_snapshot_id=reuse_snapshot_id, brief_for_date=brief_for_date)
            data = result.to_dict()
            if output_mode == "json":
                print_json_response(command, data=data)
            else:
                print(
                    f"READY brief_run_id={data['brief_run_id']} snapshot_id={data['snapshot_id']} "
                    f"subject={data.get('subject') or 'n/a'}"
                )
            return

        if action == "send":
            data = service.send(
                run_id=run_id,
                brief_for_date=brief_for_date,
                dry_run=dry_run,
                force=force,
            )
            if output_mode == "json":
                print_json_response(command, data=data)
            else:
                print(
                    f"{str(data.get('status') or 'unknown').upper()} snapshot_id={data.get('snapshot_id')} "
                    f"subject={data.get('subject') or data.get('reason') or 'n/a'}"
                )
            return

        if action == "status":
            data = service.status(limit=limit)
            if output_mode == "json":
                print_json_response(command, data=data)
            else:
                print(f"Brief DB: {data['db_path']}")
                for run in data.get("runs", []):
                    print(
                        f"- #{run['id']} snapshot={run['snapshot_id']} date={run['brief_for_date']} "
                        f"status={run['status']} sent_at={run.get('sent_at') or '—'}"
                    )
            return

        if action == "show":
            data = service.show(run_id or 0)
            if output_mode == "json":
                print_json_response(command, data=data)
            else:
                if not data:
                    print(f"Brief run {run_id} not found.")
                else:
                    print(f"Brief run #{data['id']} snapshot={data['snapshot_id']} status={data['status']}")
                    print(data.get("email_subject") or "")
                    briefing = data.get("briefing_json") or {}
                    if briefing.get("bottom_line"):
                        print(briefing["bottom_line"])
            return

        raise PortfolioError(f"Unknown brief action: {action}")
    except Exception as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)
