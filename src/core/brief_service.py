"""Stateful portfolio brief pipeline built around a DB-backed brief run."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from src.core.advisor_sidecar import AdvisorSidecarService
from src.core.brief_analysis import analyze_brief, snapshot_date_from_snapshot
from src.core.brief_render import build_briefing, render_html, render_text, send_email
from src.core.brief_scorecard import compute as compute_scorecard
from src.core.context import PortfolioContext
from src.core.errors import ConfigError
from src.schwab_client._advisor.store import AdvisorStore
from src.schwab_client.history import HistoryStore
from src.schwab_client.snapshot import collect_snapshot


@dataclass(slots=True)
class NightlyResult:
    brief_run_id: int
    snapshot_id: int
    brief_for_date: str
    status: str
    subject: str | None
    bottom_line: str | None
    fallback_mode: str | None
    advisor_run_id: int | None
    reused_advisor_issue: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "brief_run_id": self.brief_run_id,
            "snapshot_id": self.snapshot_id,
            "brief_for_date": self.brief_for_date,
            "status": self.status,
            "subject": self.subject,
            "bottom_line": self.bottom_line,
            "fallback_mode": self.fallback_mode,
            "advisor_run_id": self.advisor_run_id,
            "reused_advisor_issue": self.reused_advisor_issue,
        }


class BriefService:
    def __init__(self, *, repo_root: Path | None = None, history_store: HistoryStore | None = None) -> None:
        self.repo_root = Path(repo_root or Path.cwd())
        self.history = history_store or HistoryStore()

    def _capture_snapshot(self, *, include_market: bool = True) -> dict[str, Any]:
        from src.schwab_client.cli.context import get_cached_market_client, get_client

        client = get_client()
        market_client = None
        market_error: dict[str, str] | None = None
        if include_market:
            try:
                market_client = get_cached_market_client()
            except Exception as exc:
                market_error = {"component": "market", "message": str(exc)}
                include_market = False

        snapshot = collect_snapshot(client, include_market=include_market, market_client=market_client)
        if market_error:
            snapshot.setdefault("errors", []).append(market_error)
        history = self.history.store_snapshot(snapshot, source_command="brief-nightly")
        snapshot["history"] = history
        return snapshot

    def _load_snapshot(self, snapshot_id: int) -> dict[str, Any]:
        payload = self.history.get_snapshot_payload(snapshot_id)
        if payload is None:
            raise ConfigError(f"Snapshot {snapshot_id} not found")
        payload = dict(payload)
        payload["history"] = {
            "snapshot_id": snapshot_id,
            "db_path": str(self.history.path),
        }
        return payload

    def _capture_supplemental_context(self) -> dict[str, Any]:
        advisor = AdvisorSidecarService(repo_root=self.repo_root)
        try:
            return advisor.capture_context(include_lynch=True)
        except Exception as exc:  # pragma: no cover - defensive wrapper around live IO
            return {"errors": [f"context: {exc}"]}

    def _build_context(
        self,
        *,
        snapshot: dict[str, Any],
        existing_run: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if existing_run and isinstance(existing_run.get("context_json"), dict):
            return existing_run["context_json"]
        supplemental = self._capture_supplemental_context()
        context, _reason = PortfolioContext.from_snapshot_payload(
            snapshot,
            supplemental=supplemental,
            ytd_distributions=(supplemental or {}).get("ytd_distributions"),
        )
        return context.to_dict()

    def _build_scorecard(
        self,
        *,
        snapshot_id: int,
        snapshot: dict[str, Any],
        existing_run: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if existing_run and isinstance(existing_run.get("scorecard_json"), dict):
            return existing_run["scorecard_json"]
        total_value = ((snapshot.get("portfolio") or {}).get("summary") or {}).get("total_value")
        return compute_scorecard(self.history.path, snapshot_id=snapshot_id, total_portfolio_value=total_value)

    def _load_advisor_run(self, run_id: int | None) -> dict[str, Any] | None:
        if run_id is None:
            return None
        store = AdvisorStore()
        store.initialize()
        return store.get_run(run_id)

    def nightly(
        self,
        *,
        reuse_snapshot_id: int | None = None,
        brief_for_date: str | None = None,
        model_command: str | None = None,
        skip_advisor: bool = False,
    ) -> NightlyResult:
        snapshot = (
            self._load_snapshot(reuse_snapshot_id)
            if reuse_snapshot_id is not None
            else self._capture_snapshot()
        )
        history = snapshot.get("history") or {}
        snapshot_id = history.get("snapshot_id")
        if snapshot_id is None:
            raise ConfigError("Snapshot is missing history.snapshot_id")

        snapshot_observed_at = str(snapshot.get("generated_at") or datetime.now().isoformat())
        brief_date = brief_for_date or snapshot_date_from_snapshot(snapshot)
        existing_run = self.history.get_brief_run_by_snapshot_id(int(snapshot_id))
        context = self._build_context(snapshot=snapshot, existing_run=existing_run)
        scorecard = self._build_scorecard(snapshot_id=int(snapshot_id), snapshot=snapshot, existing_run=existing_run)

        self.history.create_or_update_brief_run(
            snapshot_id=int(snapshot_id),
            snapshot_observed_at=snapshot_observed_at,
            brief_for_date=brief_date,
            status="captured",
            context_json=context,
            scorecard_json=scorecard,
        )

        try:
            analysis_result = analyze_brief(
                snapshot=snapshot,
                scorecard=scorecard,
                context=context,
                history_store=self.history,
                model_command=model_command,
            )
            analysis = analysis_result["analysis"]
            fallback_mode = analysis_result.get("fallback_mode")

            advisor_run_id: int | None = None
            reused_issue = False
            advisor_run: dict[str, Any] | None = None
            advisor_error: str | None = None
            if not skip_advisor:
                advisor_store = AdvisorStore()
                advisor_store.initialize()
                advisor_service = AdvisorSidecarService(repo_root=self.repo_root, store=advisor_store)
                try:
                    advisor_result = advisor_service.recommend_from_context(context, model_command=model_command)
                    advisor_run_id = advisor_result.run_id
                    reused_issue = advisor_result.reused_existing_issue
                    advisor_run = advisor_store.get_run(advisor_result.run_id)
                except Exception as exc:  # pragma: no cover - live model failure should not block the brief
                    advisor_error = str(exc)
                    if context.get("errors") is None:
                        context["errors"] = []
                    context.setdefault("errors", []).append(f"advisor: {exc}")
            briefing = build_briefing(
                brief_date=brief_date,
                analysis=analysis,
                scorecard=scorecard,
                context_signals=analysis_result.get("context_signals") or {},
            )
            if advisor_error:
                briefing.setdefault("what_changed", []).append(f"Advisor unavailable: {advisor_error}")
            html = render_html(briefing=briefing, snapshot=snapshot, scorecard=scorecard, advisor=advisor_run)
            text = render_text(briefing=briefing, snapshot=snapshot, advisor=advisor_run)

            run_id = self.history.create_or_update_brief_run(
                snapshot_id=int(snapshot_id),
                snapshot_observed_at=snapshot_observed_at,
                brief_for_date=brief_date,
                status="ready",
                context_json=context,
                scorecard_json=scorecard,
                analysis_json=analysis,
                analysis_raw_response=analysis_result.get("raw_response"),
                analysis_model_command=analysis_result.get("model_command"),
                analysis_prompt_version=analysis_result.get("prompt_version"),
                advisor_run_id=advisor_run_id,
                advisor_issue_key=advisor_run.get("issue_key") if advisor_run else None,
                briefing_json=briefing,
                email_subject=briefing.get("subject"),
                email_html=html,
                email_text=text,
                fallback_mode=fallback_mode,
                last_error=advisor_error,
            )
            run = self.history.get_brief_run(run_id)
            return NightlyResult(
                brief_run_id=run_id,
                snapshot_id=int(snapshot_id),
                brief_for_date=brief_date,
                status=str(run.get("status") or "ready"),
                subject=run.get("email_subject"),
                bottom_line=(run.get("briefing_json") or {}).get("bottom_line"),
                fallback_mode=run.get("fallback_mode"),
                advisor_run_id=advisor_run_id,
                reused_advisor_issue=reused_issue,
            )
        except Exception as exc:
            self.history.create_or_update_brief_run(
                snapshot_id=int(snapshot_id),
                snapshot_observed_at=snapshot_observed_at,
                brief_for_date=brief_date,
                status="failed",
                context_json=context,
                scorecard_json=scorecard,
                last_error=str(exc),
            )
            raise

    def status(self, *, limit: int = 10) -> dict[str, Any]:
        runs = self.history.list_brief_runs(limit=limit)
        total_rows = self.history.execute_query("SELECT COUNT(*) AS count FROM brief_runs")
        run_count = int(total_rows[0]["count"]) if total_rows else 0
        return {
            "db_path": str(self.history.path),
            "run_count": run_count,
            "runs": runs,
        }

    def show(self, run_id: int) -> dict[str, Any] | None:
        return self.history.get_brief_run(run_id)

    def send(
        self,
        *,
        run_id: int | None = None,
        brief_for_date: str | None = None,
        dry_run: bool = False,
        force: bool = False,
        max_age_hours: float = 18.0,
    ) -> dict[str, Any]:
        target_date = brief_for_date or datetime.now().strftime("%Y-%m-%d")
        run = (
            self.history.get_brief_run(run_id)
            if run_id is not None
            else self.history.find_latest_brief_for_date(target_date)
        )
        if not run:
            return {"status": "skipped", "reason": "missing_brief_run", "brief_for_date": target_date}
        if run.get("sent_at") and not force:
            return {
                "status": "skipped",
                "reason": "already_sent",
                "brief_run_id": run["id"],
                "snapshot_id": run["snapshot_id"],
                "subject": run.get("email_subject"),
            }
        snapshot_observed_at = str(run.get("snapshot_observed_at") or "")
        observed_at = datetime.fromisoformat(snapshot_observed_at.replace("Z", "+00:00").replace("+00:00", ""))
        age_hours = (datetime.now() - observed_at).total_seconds() / 3600
        if age_hours >= max_age_hours and not force:
            return {
                "status": "failed",
                "reason": "stale_briefing",
                "brief_run_id": run["id"],
                "snapshot_id": run["snapshot_id"],
                "age_hours": round(age_hours, 1),
            }
        if not run.get("email_html") or not run.get("email_text") or not run.get("email_subject"):
            return {
                "status": "failed",
                "reason": "brief_not_rendered",
                "brief_run_id": run["id"],
                "snapshot_id": run["snapshot_id"],
            }
        if dry_run:
            return {
                "status": "dry_run",
                "brief_run_id": run["id"],
                "snapshot_id": run["snapshot_id"],
                "subject": run.get("email_subject"),
            }

        result = send_email(run["email_subject"], run["email_html"], run["email_text"])
        if "error" in result:
            self.history.record_brief_delivery(
                int(run["id"]),
                channel="email",
                recipient_json={},
                provider="resend",
                provider_message_id=None,
                dry_run=False,
                status="failed",
                error_text=str(result["error"]),
            )
            self.history.create_or_update_brief_run(
                snapshot_id=int(run["snapshot_id"]),
                snapshot_observed_at=str(run["snapshot_observed_at"]),
                brief_for_date=str(run["brief_for_date"]),
                status=str(run.get("status") or "ready"),
                last_error=str(result["error"]),
            )
            return {
                "status": "failed",
                "reason": str(result["error"]),
                "brief_run_id": run["id"],
                "snapshot_id": run["snapshot_id"],
                "subject": run.get("email_subject"),
            }

        self.history.record_brief_delivery(
            int(run["id"]),
            channel="email",
            recipient_json={},
            provider="resend",
            provider_message_id=result.get("id"),
            dry_run=False,
            status="sent",
            error_text=None,
        )
        self.history.create_or_update_brief_run(
            snapshot_id=int(run["snapshot_id"]),
            snapshot_observed_at=str(run["snapshot_observed_at"]),
            brief_for_date=str(run["brief_for_date"]),
            status="sent",
            sent_at=datetime.now().isoformat(timespec="seconds"),
            last_error=None,
        )
        return {
            "status": "sent",
            "brief_run_id": run["id"],
            "snapshot_id": run["snapshot_id"],
            "subject": run.get("email_subject"),
            "provider_message_id": result.get("id"),
        }


__all__ = ["BriefService", "NightlyResult"]
