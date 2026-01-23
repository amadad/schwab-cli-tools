"""
Report commands: report, snapshot.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from config.secure_account_config import secure_config
from src.core.market_service import (
    get_market_indices,
    get_market_signals,
    get_sector_performance,
    get_vix,
)
from src.core.portfolio_service import (
    analyze_allocation,
    build_account_balances,
    build_performance_report,
    build_portfolio_summary,
)

from ...auth import resolve_data_dir
from ...client import MONEY_MARKET_SYMBOLS
from ..context import get_cached_market_client, get_client
from ..output import format_currency, format_header, handle_cli_error, print_json_response

REPORT_DIR_ENV_VAR = "SCHWAB_REPORT_DIR"


def resolve_report_dir() -> Path:
    """Resolve the directory where reports are stored."""
    env_dir = os.getenv(REPORT_DIR_ENV_VAR)
    if env_dir:
        return Path(env_dir).expanduser()
    return resolve_data_dir() / "reports"


def resolve_report_path(output_path: str | None, *, timestamp: datetime | None = None) -> Path:
    """Resolve the report output path."""
    if output_path:
        path = Path(output_path).expanduser()
    else:
        ts = timestamp or datetime.now()
        path = resolve_report_dir() / f"report-{ts.strftime('%Y%m%d-%H%M%S')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_account_display_name(account_number: str) -> str:
    """Get friendly display name for account."""
    label = secure_config.get_account_label(account_number)
    if label:
        return label
    if len(account_number) > 4:
        return f"Account (...{account_number[-4:]})"
    return f"Account ({account_number})"


def sanitize_positions(positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sanitize positions by masking account numbers."""
    sanitized: list[dict[str, Any]] = []
    for pos in positions:
        entry = dict(pos)
        account_number = entry.pop("account_number", None)
        if account_number:
            entry["account_number_masked"] = secure_config.mask_account_number(
                str(account_number)
            )
            entry["account_number_last4"] = str(account_number)[-4:]
        sanitized.append(entry)
    return sanitized


def cmd_report(
    *,
    output_mode: str = "text",
    output_path: str | None = None,
    include_market: bool = True,
) -> None:
    """Generate a portfolio report and save it to disk."""
    command = "report"
    try:
        timestamp = datetime.now()
        client = get_client()
        accounts = client.get_all_accounts_full()

        summary = build_portfolio_summary(accounts, get_account_display_name, MONEY_MARKET_SYMBOLS)
        summary["positions"] = sanitize_positions(summary.get("positions", []))

        balances = build_account_balances(accounts, get_account_display_name, MONEY_MARKET_SYMBOLS)
        allocation = analyze_allocation(accounts)
        performance = build_performance_report(accounts, MONEY_MARKET_SYMBOLS)

        report = {
            "generated_at": timestamp.isoformat(),
            "portfolio": {
                "summary": summary,
                "balances": balances,
                "allocation": allocation,
                "performance": performance,
            },
        }

        warnings: list[str] = []
        if include_market:
            try:
                market_client = get_cached_market_client()
                report["market"] = get_market_signals(market_client)
            except Exception as exc:
                warnings.append("market_data_unavailable")
                report["market_error"] = str(exc)

        if warnings:
            report["warnings"] = warnings

        report_path = resolve_report_path(output_path, timestamp=timestamp)
        report_path.write_text(json.dumps(report, indent=2))

        if output_mode == "json":
            print_json_response(command, data={"report_path": str(report_path), "report": report})
            return

        print(format_header("REPORT SAVED"))
        print(f"  Path:        {report_path}")
        print(f"  Total Value: {format_currency(summary['total_value'])}")
        print(f"  Total Cash:  {format_currency(summary['total_cash'])}")
        print(f"  Positions:   {summary['position_count']}")
        if warnings:
            print(f"  Warnings:    {', '.join(warnings)}")
        print()

    except Exception as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def cmd_snapshot(*, output_mode: str = "text") -> None:
    """Get complete data snapshot for external consumers.

    Aggregates portfolio, market, and position data into a single JSON payload.
    Useful for clawdbot, external scripts, and automated reports.
    """
    command = "snapshot"
    try:
        snapshot: dict[str, Any] = {
            "generated_at": datetime.now().isoformat(),
            "errors": [],
        }

        # Use cached client for all portfolio operations
        client = get_client()

        # Portfolio data
        try:
            summary = client.get_portfolio_summary()
            summary["positions"] = sanitize_positions(summary.get("positions", []))
            snapshot["portfolio"] = {"summary": summary}
        except Exception as e:
            snapshot["portfolio"] = None
            snapshot["errors"].append(f"portfolio: {e}")

        # Positions
        try:
            positions = client.get_positions(None)
            snapshot["positions"] = {"positions": positions}
        except Exception as e:
            snapshot["positions"] = None
            snapshot["errors"].append(f"positions: {e}")

        # Balances
        try:
            balances = client.get_account_balances()
            snapshot["balances"] = {"balances": balances}
        except Exception as e:
            snapshot["balances"] = None
            snapshot["errors"].append(f"balances: {e}")

        # Allocation
        try:
            allocation = client.analyze_allocation()
            snapshot["allocation"] = allocation
        except Exception as e:
            snapshot["allocation"] = None
            snapshot["errors"].append(f"allocation: {e}")

        # Market data (use cached market client)
        try:
            market_client = get_cached_market_client()
            snapshot["market"] = get_market_signals(market_client)
        except Exception as e:
            snapshot["market"] = None
            snapshot["errors"].append(f"market: {e}")

        # VIX
        try:
            market_client = get_cached_market_client()
            snapshot["vix"] = get_vix(market_client)
        except Exception as e:
            snapshot["vix"] = None
            snapshot["errors"].append(f"vix: {e}")

        # Indices
        try:
            market_client = get_cached_market_client()
            snapshot["indices"] = get_market_indices(market_client)
        except Exception as e:
            snapshot["indices"] = None
            snapshot["errors"].append(f"indices: {e}")

        # Sectors
        try:
            market_client = get_cached_market_client()
            snapshot["sectors"] = get_sector_performance(market_client)
        except Exception as e:
            snapshot["sectors"] = None
            snapshot["errors"].append(f"sectors: {e}")

        # Clean up empty errors list
        if not snapshot["errors"]:
            del snapshot["errors"]

        if output_mode == "json":
            print_json_response(command, data=snapshot)
            return

        # Text mode summary
        print(format_header("DATA SNAPSHOT"))
        print(f"  Generated: {snapshot['generated_at']}")

        if snapshot.get("portfolio"):
            summary = snapshot["portfolio"].get("summary", {})
            print(f"\n  Portfolio: {format_currency(summary.get('total_value', 0))}")
            print(f"    Cash:      {format_currency(summary.get('total_cash', 0))}")
            print(f"    Positions: {summary.get('position_count', 0)}")

        if snapshot.get("market"):
            market = snapshot["market"]
            print(f"\n  Market: {market.get('overall', 'N/A')}")
            print(f"    Recommendation: {market.get('recommendation', 'N/A')}")

        if snapshot.get("vix"):
            vix = snapshot["vix"]
            print(f"\n  VIX: {vix.get('vix', 0):.2f} ({vix.get('signal', 'N/A')})")

        if snapshot.get("errors"):
            print(f"\n  Errors: {len(snapshot['errors'])}")
            for err in snapshot["errors"]:
                print(f"    - {err}")

        print()

    except Exception as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)
