"""History and SQL query commands."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from src.core.errors import PortfolioError

from ...history import HistoryStore
from ..output import (
    format_currency,
    format_header,
    format_percent,
    handle_cli_error,
    print_json_response,
)


def _write_json_artifact(output_path: str, payload: dict) -> Path:
    path = Path(output_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str))
    return path


def cmd_history(
    *,
    output_mode: str = "text",
    dataset: str = "runs",
    limit: int = 20,
    since: str | None = None,
    symbol: str | None = None,
    account: str | None = None,
    snapshot_id: int | None = None,
    output_path: str | None = None,
    backfill_paths: list[str] | None = None,
) -> None:
    """Query or backfill the snapshot history database."""
    command = "history"
    try:
        store = HistoryStore()

        if backfill_paths is not None:
            if snapshot_id is not None:
                raise PortfolioError("--snapshot-id cannot be combined with --import")
            if output_path is not None:
                raise PortfolioError("--output is only supported with --snapshot-id")
            result = store.import_json_paths(backfill_paths)
            if output_mode == "json":
                print_json_response(command, data=result)
                return

            print(format_header("HISTORY IMPORT"))
            print(f"  DB Path:   {result['db_path']}")
            print(f"  Imported:  {result['imported']}")
            if result.get("failures"):
                print(f"  Failures:  {len(result['failures'])}")
                for failure in result["failures"]:
                    print(f"    - {failure['path']}: {failure['message']}")
            print()
            return

        if snapshot_id is not None:
            if dataset != "runs" or since is not None or symbol is not None or account is not None:
                raise PortfolioError(
                    "--snapshot-id is an exact-read path; omit dataset/since/symbol/account filters"
                )
            payload = store.get_snapshot_payload(snapshot_id)
            if payload is None:
                raise PortfolioError(f"Snapshot {snapshot_id} not found")
            if output_path is not None:
                written_path = _write_json_artifact(output_path, payload)
                if output_mode == "json":
                    print_json_response(
                        command,
                        data={
                            "db_path": str(store.path),
                            "snapshot_id": snapshot_id,
                            "output_path": str(written_path),
                        },
                    )
                else:
                    print(format_header("SNAPSHOT EXPORTED"))
                    print(f"  DB Path:     {store.path}")
                    print(f"  Snapshot ID: {snapshot_id}")
                    print(f"  Output:      {written_path}")
                    print()
                return

            if output_mode == "json":
                print_json_response(
                    command,
                    data={
                        "db_path": str(store.path),
                        "snapshot_id": snapshot_id,
                        "snapshot": payload,
                    },
                )
            else:
                print(json.dumps(payload, indent=2, default=str))
            return

        if output_path is not None:
            raise PortfolioError("--output is only supported with --snapshot-id")

        if dataset == "runs":
            rows = store.list_runs(limit=limit, since=since)
        elif dataset == "portfolio":
            rows = store.get_portfolio_history(limit=limit, since=since)
        elif dataset == "positions":
            rows = store.get_position_history(
                symbol=symbol,
                account=account,
                limit=limit,
                since=since,
            )
        elif dataset == "market":
            rows = store.get_market_history(limit=limit, since=since)
        else:
            raise PortfolioError(f"Unsupported history dataset: {dataset}")

        if output_mode == "json":
            print_json_response(
                command,
                data={
                    "db_path": str(store.path),
                    "dataset": dataset,
                    "rows": rows,
                },
            )
            return

        if dataset == "runs":
            _print_runs(rows, db_path=str(store.path))
        elif dataset == "portfolio":
            _print_portfolio(rows, db_path=str(store.path))
        elif dataset == "positions":
            _print_positions(rows, db_path=str(store.path), symbol=symbol)
        elif dataset == "market":
            _print_market(rows, db_path=str(store.path))

    except (PortfolioError, httpx.HTTPStatusError) as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def cmd_query(sql: str, *, output_mode: str = "text") -> None:
    """Run a read-only SQL query against the history database."""
    command = "query"
    try:
        store = HistoryStore()
        rows = store.execute_query(sql)

        if output_mode == "json":
            print_json_response(
                command,
                data={
                    "db_path": str(store.path),
                    "row_count": len(rows),
                    "rows": rows,
                },
            )
            return

        print(format_header("SQL QUERY"))
        print(f"  DB Path:   {store.path}")
        print(f"  Row Count: {len(rows)}")
        print()
        for row in rows:
            print(f"  {row}")
        print()

    except (PortfolioError, httpx.HTTPStatusError) as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def _print_runs(rows: list[dict], *, db_path: str) -> None:
    print(format_header("SNAPSHOT RUNS"))
    print(f"  DB Path: {db_path}")
    if not rows:
        print("\n  No snapshot history found.\n")
        return

    for row in rows:
        print(
            f"  #{row['snapshot_id']:>4}  {row['observed_at']}  "
            f"{format_currency(row.get('total_value')):>14}  "
            f"cash {format_percent(row.get('cash_percentage')):>9}  "
            f"{row.get('source_command')}  errors={row.get('error_count', 0)}"
        )
    print()


def _print_portfolio(rows: list[dict], *, db_path: str) -> None:
    print(format_header("PORTFOLIO HISTORY"))
    print(f"  DB Path: {db_path}")
    if not rows:
        print("\n  No portfolio history found.\n")
        return

    for row in rows:
        print(
            f"  {row['observed_at']}  {format_currency(row.get('total_value')):>14}  "
            f"cash {format_currency(row.get('total_cash')):>14}  "
            f"manual {format_currency(row.get('manual_value')):>14}"
        )
    print()


def _print_positions(rows: list[dict], *, db_path: str, symbol: str | None) -> None:
    title = f"POSITION HISTORY - {symbol.upper()}" if symbol else "POSITION HISTORY"
    print(format_header(title))
    print(f"  DB Path: {db_path}")
    if not rows:
        print("\n  No position history found.\n")
        return

    for row in rows:
        print(
            f"  {row['observed_at']}  {row['symbol']:8s}  "
            f"{row.get('account_label', 'Unknown')[:20]:20s}  "
            f"qty {row.get('quantity', 0):>10.2f}  "
            f"value {format_currency(row.get('market_value')):>14}  "
            f"wt {format_percent(row.get('weight_pct')):>9}"
        )
    print()


def _print_market(rows: list[dict], *, db_path: str) -> None:
    print(format_header("MARKET HISTORY"))
    print(f"  DB Path: {db_path}")
    if not rows:
        print("\n  No market history found.\n")
        return

    for row in rows:
        print(
            f"  {row['observed_at']}  overall={row.get('overall') or 'N/A':10s}  "
            f"sentiment={row.get('market_sentiment') or 'N/A':8s}  "
            f"rotation={row.get('sector_rotation') or 'N/A':8s}  "
            f"vix={row.get('vix_value') if row.get('vix_value') is not None else 'N/A'}"
        )
    print()
