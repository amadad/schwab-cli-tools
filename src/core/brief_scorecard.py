"""Deterministic bucket scorecard for portfolio briefing."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from src.core.errors import ConfigError
from src.core.json_types import JsonObject
from src.core.policy import resolve_policy_path
from src.schwab_client.paths import resolve_history_db_path

ACCOUNT_BUCKET_MAP = {
    "ali_trading": "Trading",
    "ali_index": "Index",
    "ali_ira": "Trad IRA (Ali)",
    "ali_roth": "Roth (Ali)",
    "syra_roth": "Roth (Syra)",
    "dad_ira": "Inherited IRA (Dad)",
    "mom_ira": "Inherited IRA (Mom)",
    "mom_roth": "Inherited Roth (Mom)",
    "business": "Business",
    "ammar_esa": "Education (Ammar)",
    "hasan_esa": "Education (Hasan)",
    "laila_esa": "Education (Laila)",
    "noora_esa": "Education (Noora)",
    "403b_301": "Trad IRA (Ali)",
    "529_aam": "Education (Ammar)",
    "529_ham": "Education (Hasan)",
    "529_lzm": "Education (Laila)",
    "529_nzm": "Education (Noora)",
    "bank_582": "Cash / Bank",
    "daf_897": "DAF",
}

EXCLUDED_ACCOUNT_MATCHES = {"8214"}
INHERITED_BUCKET_MAP = {
    "Dad IRA": "Inherited IRA (Dad)",
    "Mom IRA": "Inherited IRA (Mom)",
    "Inherited Roth": "Inherited Roth (Mom)",
}


@dataclass
class BucketMetrics:
    name: str
    total_value: float = 0.0
    total_cash: float = 0.0
    accounts: list[str] = field(default_factory=list)

    @property
    def cash_pct(self) -> float:
        return (self.total_cash / self.total_value * 100) if self.total_value else 0.0


@dataclass
class BucketAlert:
    level: str
    bucket: str
    issue: str
    action: str


def is_excluded_alias(alias: str) -> bool:
    return alias in EXCLUDED_ACCOUNT_MATCHES or any(
        token in alias for token in EXCLUDED_ACCOUNT_MATCHES
    )


def extract_alias(account_key: str) -> str:
    return account_key.split(":", 1)[-1] if ":" in account_key else account_key


def resolve_policy_file() -> Path | None:
    return resolve_policy_path()


def build_bucket_policy(policy_path: Path | None = None) -> dict[str, JsonObject]:
    policy: dict[str, JsonObject] = {
        "Business": {},
        "Cash / Bank": {},
        "DAF": {},
    }
    resolved = policy_path or resolve_policy_file()
    cfg: JsonObject | None = None
    if resolved and resolved.exists():
        try:
            raw_cfg = json.loads(resolved.read_text())
        except json.JSONDecodeError as exc:
            raise ConfigError(f"Invalid policy JSON in {resolved}: {exc}") from exc
        except OSError as exc:
            raise ConfigError(f"Could not read policy file {resolved}: {exc}") from exc
        if not isinstance(raw_cfg, dict):
            raise ConfigError(f"Policy file must contain a JSON object: {resolved}")
        cfg = raw_cfg

    if cfg is not None:
        for alias, bounds in (cfg.get("cash_policies") or {}).items():
            bucket_name = ACCOUNT_BUCKET_MAP.get(alias)
            if not bucket_name:
                continue
            if isinstance(bounds, dict):
                low = float(bounds.get("low", 0.0) or 0.0)
                high = float(bounds.get("high", 100.0) or 100.0)
            elif isinstance(bounds, list | tuple) and len(bounds) == 2:
                low = float(bounds[0])
                high = float(bounds[1])
            else:
                continue
            entry = policy.setdefault(bucket_name, {})
            entry["cash_target_min"] = low / 100
            entry["cash_target_max"] = high / 100
            if low > 0:
                entry["cash_warn_low"] = low / 100
            entry["cash_warn_high"] = high / 100

        for inherited in cfg.get("inherited_ira_policies") or []:
            if not isinstance(inherited, dict):
                continue
            inherited_name = inherited.get("name")
            bucket_name = (
                INHERITED_BUCKET_MAP.get(inherited_name)
                if isinstance(inherited_name, str)
                else None
            )
            accounts = inherited.get("accounts") or []
            if not bucket_name and accounts:
                bucket_name = ACCOUNT_BUCKET_MAP.get(accounts[0])
            if not bucket_name:
                continue
            entry = policy.setdefault(bucket_name, {})
            if inherited.get("distribution_deadline"):
                entry["distribution_deadline"] = inherited["distribution_deadline"]
            if inherited.get("cash_minimum") is not None:
                entry["bucket1_min"] = float(inherited["cash_minimum"])
                entry["annual_floor_2026"] = float(inherited["cash_minimum"])

    policy.setdefault("Trading", {}).update(
        {
            "concentration_max": 0.25,
            "concentration_warn": 0.30,
        }
    )
    policy.setdefault("Index", {}).update({"concentration_max": 0.10})
    policy.setdefault("Inherited IRA (Mom)", {}).setdefault("excess_cash_warn", 200_000)
    policy.setdefault("Inherited Roth (Mom)", {}).setdefault("strategy", "defer_until_2032")

    for bucket in [
        "Education (Ammar)",
        "Education (Hasan)",
        "Education (Laila)",
        "Education (Noora)",
    ]:
        policy[bucket] = {"cash_warn_high": 0.10}

    return policy


def _connect(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(db_path))
    setattr(con, "row_factory", sqlite3.Row)  # noqa: B010
    return con


def resolve_snapshot_id(db_path: Path, snapshot_id: int | None = None) -> int | None:
    if snapshot_id is not None:
        return snapshot_id
    con = _connect(db_path)
    try:
        row = con.execute("SELECT MAX(id) AS id FROM snapshot_runs").fetchone()
    finally:
        con.close()
    return int(row["id"]) if row and row["id"] is not None else None


def load_account_snapshots(db_path: Path, snapshot_id: int | None = None) -> list[JsonObject]:
    resolved_id = resolve_snapshot_id(db_path, snapshot_id)
    if resolved_id is None:
        return []
    con = _connect(db_path)
    try:
        rows = con.execute(
            "SELECT * FROM account_snapshots WHERE snapshot_id = ?",
            (resolved_id,),
        ).fetchall()
    finally:
        con.close()
    return [dict(row) for row in rows]


def load_prior_account_snapshots(
    db_path: Path,
    *,
    snapshot_id: int | None = None,
    lookback: int = 5,
) -> list[dict[str, JsonObject]]:
    resolved_id = resolve_snapshot_id(db_path, snapshot_id)
    if resolved_id is None:
        return []

    con = _connect(db_path)
    try:
        run_ids = [
            int(row[0])
            for row in con.execute(
                "SELECT id FROM snapshot_runs WHERE id < ? ORDER BY id DESC LIMIT ?",
                (resolved_id, lookback),
            ).fetchall()
        ]
        snapshots: list[dict[str, JsonObject]] = []
        for run_id in run_ids:
            rows = con.execute(
                "SELECT * FROM account_snapshots WHERE snapshot_id = ?",
                (run_id,),
            ).fetchall()
            snapshots.append({row["account_key"]: dict(row) for row in rows})
    finally:
        con.close()
    return snapshots


def compute_buckets(account_rows: list[JsonObject]) -> dict[str, BucketMetrics]:
    buckets: dict[str, BucketMetrics] = {}
    for row in account_rows:
        alias = extract_alias(str(row["account_key"]))
        if is_excluded_alias(alias):
            continue
        bucket_name = ACCOUNT_BUCKET_MAP.get(alias, "Other")
        metrics = buckets.setdefault(bucket_name, BucketMetrics(name=bucket_name))
        metrics.total_value += row.get("total_value") or 0.0
        metrics.total_cash += row.get("total_cash") or 0.0
        metrics.accounts.append(alias)
    return buckets


def compute_bucket_deltas(
    current: dict[str, BucketMetrics],
    prior_snapshots: list[dict[str, JsonObject]],
) -> dict[str, dict[str, float | None]]:
    def bucket_value_from_snapshot(snapshot_map: dict[str, JsonObject], bucket_name: str) -> float:
        total = 0.0
        for alias, mapped_bucket in ACCOUNT_BUCKET_MAP.items():
            if mapped_bucket != bucket_name:
                continue
            for prefix in ("api:", "manual:", ""):
                key = f"{prefix}{alias}" if prefix else alias
                if key in snapshot_map:
                    total += snapshot_map[key].get("total_value") or 0.0
        return total

    deltas: dict[str, dict[str, float | None]] = {}
    for bucket_name, metrics in current.items():
        row: dict[str, float | None] = {"current": metrics.total_value}
        if prior_snapshots:
            prev_val = bucket_value_from_snapshot(prior_snapshots[0], bucket_name)
            dod_value = metrics.total_value - prev_val
            row["dod"] = dod_value
            row["dod_pct"] = ((dod_value / prev_val) * 100) if prev_val >= 100 else None
        if len(prior_snapshots) >= 5:
            week_val = bucket_value_from_snapshot(prior_snapshots[4], bucket_name)
            wow_value = metrics.total_value - week_val
            row["wow"] = wow_value
            row["wow_pct"] = ((wow_value / week_val) * 100) if week_val >= 100 else None
        deltas[bucket_name] = row
    return deltas


def run_policy_checks(
    buckets: dict[str, BucketMetrics],
    deltas: dict[str, dict[str, float | None]],
    *,
    policy: dict[str, JsonObject] | None = None,
    today: datetime | None = None,
) -> list[BucketAlert]:
    alerts: list[BucketAlert] = []
    today = today or datetime.now()
    bucket_policy = policy or build_bucket_policy()

    for bucket_name, metrics in buckets.items():
        if metrics.total_value < 500:
            continue
        rules = bucket_policy.get(bucket_name, {})

        cash_warn_high = rules.get("cash_warn_high")
        if cash_warn_high and metrics.cash_pct / 100 > cash_warn_high:
            alerts.append(
                BucketAlert(
                    level="warning",
                    bucket=bucket_name,
                    issue=f"Cash {metrics.cash_pct:.0f}% — above {cash_warn_high * 100:.0f}% target",
                    action="Review deployment plan",
                )
            )

        cash_warn_low = rules.get("cash_warn_low")
        if cash_warn_low and metrics.total_cash > 0 and metrics.cash_pct / 100 < cash_warn_low:
            alerts.append(
                BucketAlert(
                    level="warning",
                    bucket=bucket_name,
                    issue=f"Cash {metrics.cash_pct:.0f}% — below {cash_warn_low * 100:.0f}% minimum",
                    action="Review — low dry powder",
                )
            )

        if bucket_name == "Inherited IRA (Mom)":
            excess_cash_warn = rules.get("excess_cash_warn", 200_000)
            if metrics.total_cash > excess_cash_warn:
                alerts.append(
                    BucketAlert(
                        level="warning",
                        bucket=bucket_name,
                        issue=f"Cash ${metrics.total_cash:,.0f} — excess drag; target max ~${excess_cash_warn:,.0f}",
                        action="Deploy excess to equities via DCA ($50k/month plan)",
                    )
                )

        if bucket_name == "Inherited IRA (Dad)" and rules.get("distribution_deadline"):
            deadline_year = int(str(rules["distribution_deadline"])[:4])
            years_left = deadline_year - today.year
            if years_left > 0:
                floor = metrics.total_value / years_left
                bucket_min = float(rules.get("bucket1_min", floor))
                if metrics.total_cash < bucket_min * 0.5:
                    alerts.append(
                        BucketAlert(
                            level="urgent",
                            bucket=bucket_name,
                            issue=f"Cash ${metrics.total_cash:,.0f} below distribution buffer minimum ~${bucket_min:,.0f}",
                            action="Liquidate equities to refill T-bill buffer",
                        )
                    )

        delta = deltas.get(bucket_name, {})
        dod_pct = delta.get("dod_pct")
        dod = delta.get("dod")
        if (
            dod_pct is not None
            and abs(dod_pct) > 3
            and metrics.total_value > 50_000
            and dod is not None
        ):
            direction = "▲" if dod > 0 else "▼"
            alerts.append(
                BucketAlert(
                    level="info",
                    bucket=bucket_name,
                    issue=f"Large daily move: {direction}${abs(dod):,.0f} ({dod_pct:+.1f}%)",
                    action="Review — may be market-driven or data anomaly",
                )
            )

    return alerts


def _severity_rank(level: str | None) -> int:
    return {"urgent": 3, "warning": 2, "attention": 2, "info": 1}.get(level or "", 0)


def _round_optional(value: float | None, digits: int = 2) -> float | None:
    return round(value, digits) if value is not None else None


def build_scorecard(
    buckets: dict[str, BucketMetrics],
    deltas: dict[str, dict[str, float | None]],
    alerts: list[BucketAlert],
    total_portfolio_value: float,
) -> JsonObject:
    rows = []
    for bucket_name in sorted(buckets.keys()):
        metrics = buckets[bucket_name]
        if metrics.total_value < 100:
            continue
        delta = deltas.get(bucket_name, {})
        alert_level = max(
            (alert.level for alert in alerts if alert.bucket == bucket_name),
            key=_severity_rank,
            default=None,
        )
        rows.append(
            {
                "bucket": bucket_name,
                "value": round(metrics.total_value),
                "pct_of_portfolio": (
                    round(metrics.total_value / total_portfolio_value * 100, 1)
                    if total_portfolio_value
                    else 0.0
                ),
                "cash": round(metrics.total_cash),
                "cash_pct": round(metrics.cash_pct, 1),
                "dod": _round_optional(delta.get("dod"), 0),
                "dod_pct": _round_optional(delta.get("dod_pct")),
                "wow": _round_optional(delta.get("wow"), 0),
                "wow_pct": _round_optional(delta.get("wow_pct")),
                "status": alert_level or "on_track",
            }
        )

    return {
        "computed_at": datetime.now().isoformat(),
        "total_portfolio_value": round(total_portfolio_value),
        "buckets": rows,
        "alerts": [
            {
                "level": alert.level,
                "bucket": alert.bucket,
                "issue": alert.issue,
                "action": alert.action,
            }
            for alert in sorted(alerts, key=lambda item: (-_severity_rank(item.level), item.bucket))
        ],
    }


def compute(
    db_path: Path | None = None,
    *,
    snapshot_id: int | None = None,
    total_portfolio_value: float | None = None,
    policy_path: Path | None = None,
) -> JsonObject:
    resolved_db = Path(db_path).expanduser() if db_path else resolve_history_db_path()
    current_rows = load_account_snapshots(resolved_db, snapshot_id=snapshot_id)
    prior_snapshots = load_prior_account_snapshots(
        resolved_db,
        snapshot_id=snapshot_id,
        lookback=6,
    )
    buckets = compute_buckets(current_rows)
    deltas = compute_bucket_deltas(buckets, prior_snapshots)
    if total_portfolio_value is None:
        total_portfolio_value = sum(bucket.total_value for bucket in buckets.values())
    alerts = run_policy_checks(
        buckets,
        deltas,
        policy=build_bucket_policy(policy_path),
    )
    return build_scorecard(buckets, deltas, alerts, total_portfolio_value)


__all__ = [
    "ACCOUNT_BUCKET_MAP",
    "BucketAlert",
    "BucketMetrics",
    "build_bucket_policy",
    "build_scorecard",
    "compute",
    "compute_bucket_deltas",
    "compute_buckets",
    "extract_alias",
    "load_account_snapshots",
    "load_prior_account_snapshots",
    "resolve_snapshot_id",
    "run_policy_checks",
]
