"""Snapshot commands: ``snapshot`` and ``report``."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import httpx

from src.core.errors import ConfigError, PortfolioError

from ... import paths as path_utils
from ...history import HistoryStore
from ...snapshot import collect_snapshot
from ..context import get_cached_market_client, get_client
from ..output import format_currency, format_header, handle_cli_error, print_json_response

REPORT_DIR_ENV_VAR = path_utils.REPORT_DIR_ENV_VAR
resolve_report_dir = path_utils.resolve_report_dir
resolve_report_path = path_utils.resolve_report_path


def _build_snapshot(*, include_market: bool) -> dict:
    """Collect a canonical snapshot, tolerating missing market credentials."""
    client = get_client()

    market_client = None
    market_error: dict[str, str] | None = None
    if include_market:
        try:
            market_client = get_cached_market_client()
        except ConfigError as exc:
            market_error = {"component": "market", "message": str(exc)}
            include_market = False

    snapshot = collect_snapshot(
        client,
        include_market=include_market,
        market_client=market_client,
    )

    if market_error:
        snapshot.setdefault("errors", []).append(market_error)

    return snapshot


def _capture_snapshot(*, include_market: bool, source_command: str) -> dict:
    """Collect and persist a canonical snapshot."""
    snapshot = _build_snapshot(include_market=include_market)
    history = HistoryStore().store_snapshot(snapshot, source_command=source_command)
    snapshot["history"] = history
    return snapshot


def _write_snapshot_artifact(
    snapshot: dict,
    output_path: str | None,
    *,
    timestamp: datetime | None = None,
) -> Path:
    """Write a snapshot JSON artifact to disk and return its path."""
    report_path = resolve_report_path(output_path, timestamp=timestamp)
    report_path.write_text(json.dumps(snapshot, indent=2))
    return report_path


def cmd_report(
    *,
    output_mode: str = "text",
    output_path: str | None = None,
    include_market: bool = True,
) -> None:
    """Generate a canonical portfolio snapshot and save it to disk.

    ``report`` is the export-oriented wrapper around the canonical ``snapshot``
    pipeline. The snapshot is still persisted to SQLite either way.
    """
    command = "report"
    try:
        timestamp = datetime.now()
        snapshot = _capture_snapshot(include_market=include_market, source_command=command)
        report_path = _write_snapshot_artifact(snapshot, output_path, timestamp=timestamp)

        if output_mode == "json":
            print_json_response(
                command,
                data={
                    "report_path": str(report_path),
                    "history": snapshot["history"],
                    "snapshot": snapshot,
                },
            )
            return

        summary = snapshot.get("portfolio", {}).get("summary", {})
        api_accounts = snapshot.get("portfolio", {}).get("api_accounts", [])

        print(format_header("REPORT SAVED"))
        print(f"  Path:        {report_path}")
        print(f"  Snapshot ID: {snapshot['history']['snapshot_id']}")
        print(f"  Total Value: {format_currency(summary.get('total_value'))}")
        print(f"  Total Cash:  {format_currency(summary.get('total_cash'))}")
        print(f"  Positions:   {summary.get('position_count', 0)}")
        print()

        if api_accounts:
            print(format_header("ACCOUNT VALUES"))
            for account in api_accounts:
                print(
                    f"  {account['account']}: {format_currency(account.get('total_value'))}  "
                    f"(cash {format_currency(account.get('total_cash'))})"
                )
            print()

        if snapshot.get("errors"):
            print(format_header("WARNINGS"))
            for error in snapshot["errors"]:
                print(f"  - {error.get('component')}: {error.get('message')}")
            print()

    except (PortfolioError, httpx.HTTPStatusError) as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def cmd_snapshot(
    *,
    output_mode: str = "text",
    output_path: str | None = None,
    include_market: bool = True,
) -> None:
    """Capture a canonical snapshot and persist it to the history database."""
    command = "snapshot"
    try:
        snapshot = _capture_snapshot(include_market=include_market, source_command=command)
        written_path = (
            _write_snapshot_artifact(snapshot, output_path) if output_path is not None else None
        )

        if output_mode == "json":
            if written_path is None:
                print_json_response(command, data=snapshot)
            else:
                print_json_response(
                    command,
                    data={
                        "snapshot": snapshot,
                        "output_path": str(written_path),
                    },
                )
            return

        summary = snapshot.get("portfolio", {}).get("summary", {})
        market = snapshot.get("market", {}) or {}
        market_signals = market.get("signals") or {}
        vix = market.get("vix") or {}
        history = snapshot["history"]

        print(format_header("DATA SNAPSHOT"))
        print(f"  Generated:   {snapshot['generated_at']}")
        print(f"  Snapshot ID: {history['snapshot_id']}")
        print(f"  DB Path:     {history['db_path']}")
        if written_path is not None:
            print(f"  Output:      {written_path}")

        print(f"\n  Portfolio: {format_currency(summary.get('total_value'))}")
        print(f"    Cash:      {format_currency(summary.get('total_cash'))}")
        print(f"    Positions: {summary.get('position_count', 0)}")
        print(
            f"    Accounts:  {summary.get('api_account_count', 0)} API + "
            f"{summary.get('manual_account_count', 0)} manual"
        )

        if market_signals:
            print(f"\n  Market: {market_signals.get('overall', 'N/A')}")
            print(f"    Recommendation: {market_signals.get('recommendation', 'N/A')}")

        if vix:
            print(f"\n  VIX: {vix.get('vix', 0):.2f} ({vix.get('signal', 'N/A')})")

        if snapshot.get("errors"):
            print(f"\n  Errors: {len(snapshot['errors'])}")
            for error in snapshot["errors"]:
                print(f"    - {error.get('component')}: {error.get('message')}")
        print()

    except (PortfolioError, httpx.HTTPStatusError) as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)
