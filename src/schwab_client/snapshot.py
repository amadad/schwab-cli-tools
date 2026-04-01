"""Snapshot collection and normalization helpers."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import replace
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
from src.core.models import (
    AccountSnapshot,
    IndicesSnapshot,
    ManualAccount,
    ManualAccountsPayload,
    MarketSignalsSnapshot,
    MarketSnapshot,
    PortfolioSnapshot,
    PositionSnapshot,
    SectorPerformanceSnapshot,
    SnapshotDocument,
    SnapshotError,
    VixSnapshot,
)
from src.core.portfolio_service import (
    analyze_allocation_model,
    build_account_snapshots_model,
    build_portfolio_summary_model,
    build_positions_model,
)
from src.core.snapshot_service import (
    merge_portfolio_summary_model,
    summarize_manual_accounts_model,
)

from . import paths as path_utils
from .client import MONEY_MARKET_SYMBOLS, SchwabClientWrapper

MANUAL_ACCOUNTS_ENV_VAR = path_utils.MANUAL_ACCOUNTS_ENV_VAR
resolve_manual_accounts_path = path_utils.resolve_manual_accounts_path


def load_manual_accounts_model(path: str | Path | None = None) -> ManualAccountsPayload:
    """Load manual account metadata used for holistic portfolio snapshots."""
    resolved_path: Path | None
    if path is None:
        resolved_path = resolve_manual_accounts_path()
    else:
        resolved_path = Path(path).expanduser()

    if resolved_path is None or not resolved_path.exists():
        return ManualAccountsPayload.empty(
            source_path=str(resolved_path) if resolved_path else None,
        )

    with resolved_path.open() as handle:
        payload = json.load(handle)

    accounts = [ManualAccount.from_dict(account) for account in payload.get("accounts", [])]
    return ManualAccountsPayload(
        source_path=str(resolved_path),
        last_updated=payload.get("_last_updated"),
        accounts=accounts,
        summary=summarize_manual_accounts_model(accounts),
    )


def load_manual_accounts(path: str | Path | None = None) -> dict[str, Any]:
    """Load manual account metadata used for holistic portfolio snapshots."""
    return load_manual_accounts_model(path).to_dict()


def get_account_display_name(account_number: str) -> str:
    """Get friendly display name for account."""
    label = secure_config.get_account_label(account_number)
    if label:
        return label
    if len(account_number) > 4:
        return f"Account (...{account_number[-4:]})"
    return f"Account ({account_number})"


def _sanitize_position_model(position: PositionSnapshot) -> PositionSnapshot:
    account_number = position.account_number
    sanitized = replace(position, account_number=None)

    if not account_number:
        return sanitized

    account_info = secure_config.get_account_info_by_number(str(account_number))
    account_alias = account_info.alias if account_info else position.account_alias
    return replace(
        sanitized,
        account_alias=account_alias,
        account_number_masked=secure_config.mask_account_number(str(account_number)),
        account_number_last4=str(account_number)[-4:],
    )


def _sanitize_positions_model(
    positions: Sequence[PositionSnapshot | dict[str, Any]],
) -> list[PositionSnapshot]:
    sanitized: list[PositionSnapshot] = []
    for position in positions:
        model = (
            position
            if isinstance(position, PositionSnapshot)
            else PositionSnapshot.from_dict(position)
        )
        sanitized.append(_sanitize_position_model(model))
    return sanitized


def sanitize_positions(positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sanitize positions by masking account numbers."""
    return [position.to_dict() for position in _sanitize_positions_model(positions)]


def _sanitize_account_snapshots_model(
    accounts: Sequence[AccountSnapshot | dict[str, Any]],
) -> list[AccountSnapshot]:
    sanitized: list[AccountSnapshot] = []

    for account in accounts:
        model = (
            account if isinstance(account, AccountSnapshot) else AccountSnapshot.from_dict(account)
        )
        account_number = model.account_number
        positions = _sanitize_positions_model(model.positions)
        sanitized_account = replace(model, account_number=None, positions=positions)

        if account_number:
            account_info = secure_config.get_account_info_by_number(str(account_number))
            sanitized_account = replace(
                sanitized_account,
                account_alias=account_info.alias if account_info else model.account_alias,
                account_number_masked=secure_config.mask_account_number(str(account_number)),
                account_number_last4=str(account_number)[-4:],
            )

        sanitized.append(sanitized_account)

    return sanitized


def sanitize_account_snapshots(accounts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sanitize account snapshots by masking account identifiers."""
    return [account.to_dict() for account in _sanitize_account_snapshots_model(accounts)]


def _build_market_snapshot_model(
    market_client: Any,
) -> tuple[MarketSnapshot, list[SnapshotError]]:
    """Collect market context with per-component error isolation."""
    market_snapshot = MarketSnapshot()
    errors: list[SnapshotError] = []

    try:
        market_snapshot.signals = MarketSignalsSnapshot.from_dict(get_market_signals(market_client))
    except Exception as exc:  # pragma: no cover - defensive wrapper
        errors.append(SnapshotError(component="market.signals", message=str(exc)))

    try:
        market_snapshot.vix = VixSnapshot.from_dict(get_vix(market_client))
    except Exception as exc:  # pragma: no cover - defensive wrapper
        errors.append(SnapshotError(component="market.vix", message=str(exc)))

    try:
        market_snapshot.indices = IndicesSnapshot.from_dict(get_market_indices(market_client))
    except Exception as exc:  # pragma: no cover - defensive wrapper
        errors.append(SnapshotError(component="market.indices", message=str(exc)))

    try:
        market_snapshot.sectors = SectorPerformanceSnapshot.from_dict(
            get_sector_performance(market_client)
        )
    except Exception as exc:  # pragma: no cover - defensive wrapper
        errors.append(SnapshotError(component="market.sectors", message=str(exc)))

    return market_snapshot, errors


def collect_snapshot_document(
    client: SchwabClientWrapper,
    *,
    include_market: bool = True,
    include_manual_accounts: bool = True,
    market_client: Any | None = None,
    manual_accounts_path: str | Path | None = None,
    timestamp: datetime | None = None,
) -> SnapshotDocument:
    """Collect a canonical typed snapshot document."""
    observed_at = (timestamp or datetime.now()).isoformat()
    errors: list[SnapshotError] = []

    accounts = client.get_all_accounts_full()
    api_summary = build_portfolio_summary_model(
        accounts,
        get_account_display_name,
        MONEY_MARKET_SYMBOLS,
    )
    api_account_snapshots = build_account_snapshots_model(
        accounts,
        get_account_display_name,
        MONEY_MARKET_SYMBOLS,
    )
    api_positions = build_positions_model(
        accounts,
        get_account_display_name,
        money_market_symbols=MONEY_MARKET_SYMBOLS,
        include_account_number=True,
    )
    allocation = analyze_allocation_model(accounts)

    manual_accounts = ManualAccountsPayload.empty()
    if include_manual_accounts:
        try:
            manual_accounts = load_manual_accounts_model(manual_accounts_path)
        except Exception as exc:  # pragma: no cover - defensive wrapper
            errors.append(SnapshotError(component="portfolio.manual_accounts", message=str(exc)))

    combined_summary = merge_portfolio_summary_model(api_summary, manual_accounts.accounts)

    market_snapshot = None
    if include_market:
        if market_client is None:
            errors.append(
                SnapshotError(
                    component="market",
                    message="Market data requested but no market client was provided.",
                )
            )
        else:
            market_snapshot, market_errors = _build_market_snapshot_model(market_client)
            errors.extend(market_errors)

    return SnapshotDocument(
        generated_at=observed_at,
        portfolio=PortfolioSnapshot(
            summary=combined_summary,
            api_accounts=_sanitize_account_snapshots_model(api_account_snapshots),
            manual_accounts=manual_accounts,
            positions=_sanitize_positions_model(api_positions),
            allocation=allocation,
        ),
        market=market_snapshot,
        errors=errors,
    )


def collect_snapshot(
    client: SchwabClientWrapper,
    *,
    include_market: bool = True,
    include_manual_accounts: bool = True,
    market_client: Any | None = None,
    manual_accounts_path: str | Path | None = None,
    timestamp: datetime | None = None,
) -> dict[str, Any]:
    """Collect a canonical snapshot document.

    The resulting document is designed to be both persisted in SQLite and saved
    as JSON for human review or downstream automation.
    """
    return collect_snapshot_document(
        client,
        include_market=include_market,
        include_manual_accounts=include_manual_accounts,
        market_client=market_client,
        manual_accounts_path=manual_accounts_path,
        timestamp=timestamp,
    ).to_dict()
