#!/usr/bin/env python
"""Build ML features and labels from canonical snapshot history.

Reads every snapshot in private/history/schwab_history.db, extracts a
feature vector per day from the stored raw JSON, and labels day t by
running the policy engine against day t+1.

Run with: uv run python scripts/prepare_ml_data.py
"""

from __future__ import annotations

import csv
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.policy import PolicyConfig, evaluate_policy, load_policy_config  # noqa: E402

DB_PATH = PROJECT_ROOT / "private" / "history" / "schwab_history.db"
ACCOUNTS_PATH = PROJECT_ROOT / "config" / "accounts.json"
OUT_DIR = PROJECT_ROOT / "data" / "ml"

# History snapshots label accounts like "Mom IRA (...8652)" — grab the last-4.
LAST4_RE = re.compile(r"\(\.\.\.(\d{4})\)")


def load_alias_resolver(accounts_path: Path) -> dict[str, str]:
    """Return {last4: alias} from config/accounts.json so history labels can
    be routed to the policy engine's alias keys (ali_trading, mom_ira, …)."""
    data = json.loads(accounts_path.read_text())
    resolver: dict[str, str] = {}
    for alias, info in data.get("accounts", {}).items():
        num = str(info.get("account_number") or "")
        if len(num) >= 4:
            resolver[num[-4:]] = alias
    return resolver


def resolve_alias(label: str, resolver: dict[str, str]) -> str | None:
    """Extract the last-4 from an account label and return the canonical alias."""
    match = LAST4_RE.search(label or "")
    if not match:
        return None
    return resolver.get(match.group(1))


def load_snapshots(db_path: Path) -> list[tuple[str, dict[str, Any]]]:
    """Return (observed_at, parsed raw_json) for one snapshot per calendar day.

    When multiple snapshots exist on the same day (e.g. 15 runs on 2026-03-13),
    pick the last one so day t → day t+1 labeling reflects real day-over-day
    moves instead of minute-over-minute duplicates.
    """
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            "SELECT observed_at, raw_json FROM snapshot_runs "
            "WHERE raw_json IS NOT NULL ORDER BY observed_at ASC"
        ).fetchall()
    finally:
        con.close()

    per_day: dict[str, tuple[str, str]] = {}
    for obs, raw in rows:
        day = obs[:10]  # YYYY-MM-DD prefix of ISO-8601 timestamp
        per_day[day] = (obs, raw)
    return [
        (obs, json.loads(raw))
        for day, (obs, raw) in sorted(per_day.items())
    ]


def snapshot_features(
    observed_at: str, snap: dict[str, Any], resolver: dict[str, str]
) -> dict[str, Any]:
    """Flatten one snapshot into a feature vector.

    Per-account columns are keyed by canonical alias (ali_trading, mom_ira, …)
    rather than display label, so they stay stable across label renames.
    Accounts with no matching alias are skipped.
    """
    portfolio = snap.get("portfolio") or {}
    summary = portfolio.get("summary") or {}
    api_accounts = portfolio.get("api_accounts") or []

    features: dict[str, Any] = {
        "observed_at": observed_at,
        "total_value": float(summary.get("total_value") or 0.0),
        "total_cash": float(summary.get("total_cash") or 0.0),
        "total_invested": float(summary.get("total_invested") or 0.0),
        "total_unrealized_pl": float(summary.get("total_unrealized_pl") or 0.0),
        "cash_percentage": float(summary.get("cash_percentage") or 0.0),
        "account_count": int(summary.get("account_count") or 0),
        "position_count": int(summary.get("position_count") or 0),
    }
    for acct in api_accounts:
        alias = resolve_alias(acct.get("account") or "", resolver)
        if not alias:
            continue
        total = float(acct.get("total_value") or 0.0)
        cash = float(acct.get("total_cash") or 0.0)
        features[f"cash_pct__{alias}"] = (cash / total * 100.0) if total > 0 else 0.0
    return features


def label_for_next_day(
    snap: dict[str, Any],
    policy_config: PolicyConfig,
    resolver: dict[str, str],
) -> int:
    """Return 1 if the snapshot triggers any critical/warning policy alert.

    Accounts are keyed by alias so the policy engine's bucket rules match.
    YTD distributions aren't tracked in the history DB, so pacing alerts
    are best-effort until a backfill exists.
    """
    portfolio = snap.get("portfolio") or {}
    summary = portfolio.get("summary") or {}
    api_accounts = portfolio.get("api_accounts") or []

    account_balances: dict[str, dict[str, float]] = {}
    for acct in api_accounts:
        alias = resolve_alias(acct.get("account") or "", resolver)
        if not alias:
            continue
        account_balances[alias] = {
            "total_value": float(acct.get("total_value") or 0.0),
            "cash": float(acct.get("total_cash") or 0.0),
        }

    delta = evaluate_policy(
        account_balances=account_balances,
        ytd_distributions={},
        total_cash_pct=float(summary.get("cash_percentage") or 0.0),
        policy_config=policy_config,
    )
    return 1 if (delta.critical_count + delta.warning_count) > 0 else 0


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    print(f"Reading {DB_PATH}")
    snapshots = load_snapshots(DB_PATH)
    if not snapshots:
        print("No snapshots found. Exiting.", file=sys.stderr)
        return 1
    print(
        f"Loaded {len(snapshots)} daily snapshots "
        f"({snapshots[0][0][:10]} → {snapshots[-1][0][:10]})"
    )

    resolver = load_alias_resolver(ACCOUNTS_PATH)
    print(f"Loaded alias resolver with {len(resolver)} accounts")

    policy_config = load_policy_config()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    all_features = [snapshot_features(obs, snap, resolver) for obs, snap in snapshots]

    all_labels: list[dict[str, Any]] = []
    for i, (obs, _) in enumerate(snapshots):
        if i + 1 < len(snapshots):
            label = label_for_next_day(snapshots[i + 1][1], policy_config, resolver)
        else:
            label = -1  # no next day available
        all_labels.append({"observed_at": obs, "label": label})

    # Sparse per-account columns: collect the union, preserving first-seen order
    feature_cols: list[str] = []
    seen: set[str] = set()
    for feat in all_features:
        for col in feat:
            if col not in seen:
                feature_cols.append(col)
                seen.add(col)

    features_path = OUT_DIR / "features.csv"
    labels_path = OUT_DIR / "labels.csv"
    write_csv(features_path, feature_cols, all_features)
    write_csv(labels_path, ["observed_at", "label"], all_labels)

    pos = sum(1 for r in all_labels if r["label"] == 1)
    neg = sum(1 for r in all_labels if r["label"] == 0)
    unk = sum(1 for r in all_labels if r["label"] == -1)
    print(f"Wrote {features_path} ({len(all_features)} rows, {len(feature_cols)} cols)")
    print(f"Wrote {labels_path} (positive={pos}, negative={neg}, unknown={unk})")
    print(
        "Note: YTD distributions are not tracked in the history DB, "
        "so distribution-pacing alerts are best-effort."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
