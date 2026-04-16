"""Helpers for canonical portfolio snapshot documents."""

from __future__ import annotations

from collections.abc import Sequence

from src.core.json_types import JsonObject
from src.core.models import ManualAccount, ManualAccountsSummary, PortfolioSummary


def summarize_manual_accounts_model(
    manual_accounts: Sequence[ManualAccount | JsonObject],
) -> ManualAccountsSummary:
    """Summarize manual account values for holistic reporting."""
    accounts = [
        account if isinstance(account, ManualAccount) else ManualAccount.from_dict(account)
        for account in manual_accounts
    ]

    total_value = 0.0
    total_cash = 0.0
    by_category: dict[str, float] = {}

    for account in accounts:
        value = float(account.value or 0)
        category = account.category or "unknown"
        total_value += value
        by_category[category] = by_category.get(category, 0.0) + value
        if category == "cash":
            total_cash += value

    return ManualAccountsSummary(
        total_value=total_value,
        total_cash=total_cash,
        total_invested=total_value - total_cash,
        account_count=len(accounts),
        by_category=by_category,
    )


def merge_portfolio_summary_model(
    api_summary: PortfolioSummary | JsonObject,
    manual_accounts: Sequence[ManualAccount | JsonObject],
) -> PortfolioSummary:
    """Merge API portfolio summary with manual account totals."""
    summary = (
        api_summary
        if isinstance(api_summary, PortfolioSummary)
        else PortfolioSummary.from_dict(api_summary)
    )
    manual_summary = summarize_manual_accounts_model(manual_accounts)

    api_value = summary.api_value if summary.api_value is not None else summary.total_value
    api_cash = summary.total_cash
    manual_value = manual_summary.total_value
    manual_cash = manual_summary.total_cash

    total_value = api_value + manual_value
    total_cash = api_cash + manual_cash

    api_account_count = (
        summary.api_account_count
        if summary.api_account_count is not None
        else summary.account_count
    )
    manual_account_count = manual_summary.account_count

    return PortfolioSummary(
        total_value=total_value,
        api_value=api_value,
        manual_value=manual_value,
        total_cash=total_cash,
        manual_cash=manual_cash,
        total_invested=total_value - total_cash,
        total_unrealized_pl=summary.total_unrealized_pl,
        cash_percentage=(total_cash / total_value * 100) if total_value > 0 else 0.0,
        account_count=api_account_count + manual_account_count,
        api_account_count=api_account_count,
        manual_account_count=manual_account_count,
        position_count=summary.position_count,
        positions=list(summary.positions),
    )
