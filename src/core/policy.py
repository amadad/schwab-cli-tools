"""Policy-aware delta engine for portfolio context.

Policy rules are loaded from a local JSON profile so the public repo can ship a
sanitized template while each operator keeps private account aliases and
thresholds in ignored files such as ``private/policy.json``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from src.core.errors import ConfigError

POLICY_PATH_ENV_VAR = "SCHWAB_POLICY_PATH"
DEFAULT_POLICY_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "config" / "policy.template.json"
DEFAULT_PRIVATE_POLICY_PATH = Path.cwd() / "private" / "policy.json"


@dataclass(slots=True)
class BucketPolicy:
    """Policy definition for a single bucket."""

    name: str
    accounts: list[str]
    bucket_type: str  # "growth", "depletion", "passive", "education", "business"
    cash_target_low: float = 0.0  # percentage
    cash_target_high: float = 100.0  # percentage
    distribution_deadline: date | None = None
    annual_floor: float | None = None  # dollar amount
    years_remaining: int | None = None
    cash_minimum: float | None = None  # dollar amount for distribution buffer


@dataclass(slots=True)
class PolicyConfig:
    """Loaded policy configuration for portfolio analysis."""

    inherited_ira_policies: list[BucketPolicy] = field(default_factory=list)
    cash_policies: dict[str, tuple[float, float]] = field(default_factory=dict)
    portfolio_cash_target: tuple[float, float] = (15.0, 30.0)
    calendar: dict[int, str] = field(default_factory=dict)
    source_path: str | None = None

    def tracked_distribution_accounts(self) -> set[str]:
        """Return accounts that should be scanned for distribution pacing."""
        tracked: set[str] = set()
        for policy in self.inherited_ira_policies:
            if policy.distribution_deadline is not None:
                tracked.update(policy.accounts)
        return tracked


@dataclass(slots=True)
class PolicyAlert:
    """A single policy violation or attention item."""

    bucket: str
    severity: str  # "critical", "warning", "info"
    category: str  # "distribution_pace", "cash_level", "deadline", "calendar"
    message: str
    metric: str | None = None
    current_value: float | None = None
    target_value: float | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PolicyAlert:
        return cls(
            bucket=str(data.get("bucket") or "unknown"),
            severity=str(data.get("severity") or "info"),
            category=str(data.get("category") or "unknown"),
            message=str(data.get("message") or ""),
            metric=str(data["metric"]) if data.get("metric") is not None else None,
            current_value=(
                float(data["current_value"]) if data.get("current_value") is not None else None
            ),
            target_value=(
                float(data["target_value"]) if data.get("target_value") is not None else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "bucket": self.bucket,
            "severity": self.severity,
            "category": self.category,
            "message": self.message,
        }
        if self.metric:
            d["metric"] = self.metric
        if self.current_value is not None:
            d["current_value"] = self.current_value
        if self.target_value is not None:
            d["target_value"] = self.target_value
        return d


@dataclass(slots=True)
class DistributionPacing:
    """Distribution pacing status for an inherited IRA."""

    account: str
    ytd_distributions: float
    annual_floor: float
    pacing_pct: float
    years_remaining: int
    deadline: date
    on_track: bool

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DistributionPacing:
        return cls(
            account=str(data.get("account") or "unknown"),
            ytd_distributions=float(data.get("ytd_distributions", 0.0) or 0.0),
            annual_floor=float(data.get("annual_floor", 0.0) or 0.0),
            pacing_pct=float(data.get("pacing_pct", 0.0) or 0.0),
            years_remaining=int(data.get("years_remaining", 0) or 0),
            deadline=date.fromisoformat(str(data.get("deadline"))),
            on_track=bool(data.get("on_track", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "account": self.account,
            "ytd_distributions": self.ytd_distributions,
            "annual_floor": self.annual_floor,
            "pacing_pct": round(self.pacing_pct, 1),
            "years_remaining": self.years_remaining,
            "deadline": self.deadline.isoformat(),
            "on_track": self.on_track,
        }


@dataclass(slots=True)
class PolicyDelta:
    """Complete policy comparison result."""

    alerts: list[PolicyAlert] = field(default_factory=list)
    distribution_pacing: list[DistributionPacing] = field(default_factory=list)
    calendar_actions: list[str] = field(default_factory=list)
    checked_at: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PolicyDelta:
        return cls(
            alerts=[PolicyAlert.from_dict(alert) for alert in data.get("alerts", [])],
            distribution_pacing=[
                DistributionPacing.from_dict(pacing)
                for pacing in data.get("distribution_pacing", [])
            ],
            calendar_actions=[str(item) for item in data.get("calendar_actions", [])],
            checked_at=str(data.get("checked_at") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "alerts": [a.to_dict() for a in self.alerts],
            "distribution_pacing": [p.to_dict() for p in self.distribution_pacing],
            "calendar_actions": self.calendar_actions,
            "checked_at": self.checked_at,
        }

    @property
    def critical_count(self) -> int:
        return sum(1 for a in self.alerts if a.severity == "critical")

    @property
    def warning_count(self) -> int:
        return sum(1 for a in self.alerts if a.severity == "warning")

    def summary_lines(self) -> list[str]:
        """Return human-readable summary for embedding in prompts."""
        lines = []
        for pacing in self.distribution_pacing:
            status = "on track" if pacing.on_track else "BEHIND"
            lines.append(
                f"- {pacing.account}: ${pacing.ytd_distributions:,.0f} / "
                f"${pacing.annual_floor:,.0f} ({pacing.pacing_pct:.0f}%) — {status}"
            )
        for alert in self.alerts:
            icon = {"critical": "[!]", "warning": "[~]", "info": "[-]"}.get(
                alert.severity, "[-]"
            )
            lines.append(f"{icon} {alert.bucket}: {alert.message}")
        for calendar_action in self.calendar_actions:
            lines.append(f"[calendar] {calendar_action}")
        return lines


def _default_policy_config() -> PolicyConfig:
    """Return a generic, non-personal default policy profile."""
    return PolicyConfig(
        inherited_ira_policies=[
            BucketPolicy(
                name="Inherited IRA 1",
                accounts=["acct_inherited_ira_1"],
                bucket_type="depletion",
                distribution_deadline=date(2030, 12, 31),
                cash_minimum=85_000,
            ),
            BucketPolicy(
                name="Inherited IRA 2",
                accounts=["acct_inherited_ira_2"],
                bucket_type="depletion",
                distribution_deadline=date(2034, 12, 31),
                cash_minimum=100_000,
            ),
        ],
        cash_policies={
            "acct_taxable_trading": (30.0, 50.0),
            "acct_taxable_index": (0.0, 5.0),
            "acct_traditional_ira": (5.0, 10.0),
            "acct_roth_ira": (0.0, 5.0),
            "acct_family_roth": (0.0, 5.0),
            "acct_inherited_roth": (0.0, 10.0),
        },
        portfolio_cash_target=(15.0, 30.0),
        calendar={
            1: "Record inherited IRA balances. Calculate annual distribution floors.",
            3: "Verify inherited IRA distribution schedules and deployment plans.",
            6: "YTD distribution check — should be at least 50% of annual floor.",
            9: "YTD distribution check — should be at least 80% of annual floor.",
            10: "Review tax bracket headroom and any year-end true-up distributions.",
            12: "Finalize distributions, confirm withholding, and update the policy file.",
        },
        source_path=str(DEFAULT_POLICY_TEMPLATE_PATH),
    )


def resolve_policy_path(path: str | Path | None = None) -> Path | None:
    """Resolve the policy profile path.

    Preference order:
    1. explicit ``path`` argument
    2. ``SCHWAB_POLICY_PATH``
    3. ``./private/policy.json`` when present
    4. tracked ``config/policy.template.json``
    """
    if path is not None:
        return Path(path).expanduser()

    env_path = os.getenv(POLICY_PATH_ENV_VAR)
    if env_path:
        return Path(env_path).expanduser()

    if DEFAULT_PRIVATE_POLICY_PATH.exists():
        return DEFAULT_PRIVATE_POLICY_PATH

    if DEFAULT_POLICY_TEMPLATE_PATH.exists():
        return DEFAULT_POLICY_TEMPLATE_PATH

    return None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def _parse_bucket_policy(data: dict[str, Any]) -> BucketPolicy:
    return BucketPolicy(
        name=str(data.get("name") or "Unnamed Bucket"),
        accounts=[str(account) for account in data.get("accounts", [])],
        bucket_type=str(data.get("bucket_type") or "unknown"),
        cash_target_low=float(data.get("cash_target_low", 0.0) or 0.0),
        cash_target_high=float(data.get("cash_target_high", 100.0) or 100.0),
        distribution_deadline=_parse_date(data.get("distribution_deadline")),
        annual_floor=(
            float(data["annual_floor"])
            if data.get("annual_floor") is not None
            else None
        ),
        years_remaining=(
            int(data["years_remaining"])
            if data.get("years_remaining") is not None
            else None
        ),
        cash_minimum=(
            float(data["cash_minimum"])
            if data.get("cash_minimum") is not None
            else None
        ),
    )


def _parse_cash_policies(data: dict[str, Any]) -> dict[str, tuple[float, float]]:
    policies: dict[str, tuple[float, float]] = {}
    for account, value in data.items():
        if isinstance(value, dict):
            low = float(value.get("low", 0.0) or 0.0)
            high = float(value.get("high", 100.0) or 100.0)
        elif isinstance(value, list | tuple) and len(value) == 2:
            low = float(value[0])
            high = float(value[1])
        else:
            raise ConfigError(
                f"Invalid cash policy for {account!r}. Expected {{low, high}} or [low, high]."
            )
        policies[str(account)] = (low, high)
    return policies


def load_policy_config(path: str | Path | None = None) -> PolicyConfig:
    """Load policy configuration from JSON, falling back to a generic template."""
    resolved_path = resolve_policy_path(path)
    default_config = _default_policy_config()

    explicit_path_requested = path is not None or os.getenv(POLICY_PATH_ENV_VAR)
    if resolved_path is None:
        return default_config

    if not resolved_path.exists():
        if explicit_path_requested:
            raise ConfigError(f"Policy file not found: {resolved_path}")
        return default_config

    try:
        payload = json.loads(resolved_path.read_text())
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid policy JSON in {resolved_path}: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"Could not read policy file {resolved_path}: {exc}") from exc

    inherited_payload = payload.get("inherited_ira_policies", [])
    calendar_payload = payload.get("calendar", {})
    portfolio_cash_target_payload = payload.get("portfolio_cash_target", {})

    inherited_ira_policies = [
        _parse_bucket_policy(entry)
        for entry in inherited_payload
        if isinstance(entry, dict)
    ]
    cash_policies = _parse_cash_policies(payload.get("cash_policies", {}))

    if isinstance(portfolio_cash_target_payload, dict):
        portfolio_cash_target = (
            float(portfolio_cash_target_payload.get("low", default_config.portfolio_cash_target[0])),
            float(portfolio_cash_target_payload.get("high", default_config.portfolio_cash_target[1])),
        )
    elif (
        isinstance(portfolio_cash_target_payload, list | tuple)
        and len(portfolio_cash_target_payload) == 2
    ):
        portfolio_cash_target = (
            float(portfolio_cash_target_payload[0]),
            float(portfolio_cash_target_payload[1]),
        )
    else:
        portfolio_cash_target = default_config.portfolio_cash_target

    calendar = {int(month): str(message) for month, message in calendar_payload.items()}

    return PolicyConfig(
        inherited_ira_policies=(
            inherited_ira_policies or default_config.inherited_ira_policies
        ),
        cash_policies=cash_policies or default_config.cash_policies,
        portfolio_cash_target=portfolio_cash_target,
        calendar=calendar or default_config.calendar,
        source_path=str(resolved_path),
    )


def _compute_floor(balance: float, deadline: date, today: date | None = None) -> tuple[float, int]:
    """Compute annual distribution floor and years remaining."""
    today = today or date.today()
    years = deadline.year - today.year
    if years < 1:
        years = 1
    return balance / years, years


def evaluate_policy(
    account_balances: dict[str, dict[str, float]],
    ytd_distributions: dict[str, float],
    total_cash_pct: float,
    today: date | None = None,
    policy_config: PolicyConfig | None = None,
) -> PolicyDelta:
    """Evaluate portfolio against policy rules."""
    today = today or date.today()
    policy = policy_config or load_policy_config()
    delta = PolicyDelta(checked_at=datetime.now().isoformat())

    for bucket_policy in policy.inherited_ira_policies:
        for account in bucket_policy.accounts:
            balance_info = account_balances.get(account)
            if not balance_info:
                continue

            deadline = bucket_policy.distribution_deadline
            if deadline is None:
                continue

            balance = balance_info.get("total_value", 0)
            cash = balance_info.get("cash", 0)
            floor, years = _compute_floor(balance, deadline, today)
            ytd = ytd_distributions.get(account, 0)
            pacing = (ytd / floor * 100) if floor > 0 else 0

            month = today.month
            if month >= 9:
                expected_pct = 80.0
            elif month >= 6:
                expected_pct = 50.0
            else:
                expected_pct = month / 12 * 100

            on_track = pacing >= expected_pct * 0.9

            delta.distribution_pacing.append(
                DistributionPacing(
                    account=account,
                    ytd_distributions=ytd,
                    annual_floor=floor,
                    pacing_pct=pacing,
                    years_remaining=years,
                    deadline=deadline,
                    on_track=on_track,
                )
            )

            if not on_track:
                needed = floor - ytd
                delta.alerts.append(
                    PolicyAlert(
                        bucket=bucket_policy.name,
                        severity="critical" if month >= 9 else "warning",
                        category="distribution_pace",
                        message=(
                            f"YTD ${ytd:,.0f} vs floor ${floor:,.0f} ({pacing:.0f}%). "
                            f"Need ${needed:,.0f} more."
                        ),
                        metric="ytd_vs_floor",
                        current_value=ytd,
                        target_value=floor,
                    )
                )

            if bucket_policy.cash_minimum and cash < bucket_policy.cash_minimum:
                delta.alerts.append(
                    PolicyAlert(
                        bucket=bucket_policy.name,
                        severity="warning",
                        category="cash_level",
                        message=(
                            f"Cash ${cash:,.0f} below minimum "
                            f"${bucket_policy.cash_minimum:,.0f}"
                        ),
                        metric="cash_buffer",
                        current_value=cash,
                        target_value=bucket_policy.cash_minimum,
                    )
                )

    for account, (low, high) in policy.cash_policies.items():
        balance_info = account_balances.get(account)
        if not balance_info:
            continue
        total = balance_info.get("total_value", 0)
        cash = balance_info.get("cash", 0)
        if total <= 0:
            continue
        cash_pct = cash / total * 100

        if cash_pct > high + 5:
            delta.alerts.append(
                PolicyAlert(
                    bucket=account,
                    severity="warning",
                    category="cash_level",
                    message=f"Cash {cash_pct:.0f}% above target {high:.0f}%",
                    metric="cash_pct",
                    current_value=cash_pct,
                    target_value=high,
                )
            )
        elif cash_pct < low - 5:
            delta.alerts.append(
                PolicyAlert(
                    bucket=account,
                    severity="warning",
                    category="cash_level",
                    message=f"Cash {cash_pct:.0f}% below target {low:.0f}%",
                    metric="cash_pct",
                    current_value=cash_pct,
                    target_value=low,
                )
            )

    portfolio_low, portfolio_high = policy.portfolio_cash_target
    if total_cash_pct > portfolio_high:
        delta.alerts.append(
            PolicyAlert(
                bucket="portfolio",
                severity="warning",
                category="cash_level",
                message=f"Total cash {total_cash_pct:.1f}% above {portfolio_high:.0f}% target",
                metric="portfolio_cash_pct",
                current_value=total_cash_pct,
                target_value=portfolio_high,
            )
        )

    month = today.month
    if month in policy.calendar:
        delta.calendar_actions.append(policy.calendar[month])
    next_month = month + 1 if month < 12 else 1
    if next_month in policy.calendar:
        delta.calendar_actions.append(f"(upcoming) {policy.calendar[next_month]}")

    return delta


__all__ = [
    "BucketPolicy",
    "DistributionPacing",
    "POLICY_PATH_ENV_VAR",
    "PolicyAlert",
    "PolicyConfig",
    "PolicyDelta",
    "evaluate_policy",
    "load_policy_config",
    "resolve_policy_path",
]
