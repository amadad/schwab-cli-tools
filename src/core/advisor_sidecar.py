"""Recommendation-engine journal and evaluator.

The legacy module name is retained for compatibility while the repo terminology shifts
from "advisor sidecar" to "recommendation engine".
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from src.core.advisor_models import AdvisorRecommendation
from src.core.advisor_prompts import RECOMMEND_PROMPT
from src.core.advisor_scoring import classify_outcome, compute_policy_health_score
from src.core.context import PortfolioContext
from src.core.json_types import JsonObject, as_json_array, as_json_object
from src.schwab_client._advisor.store import AdvisorStore
from src.schwab_client.history import HistoryStore

ADVISOR_MODEL_COMMAND_ENV_VAR = "SCHWAB_ADVISOR_MODEL_COMMAND"
DEFAULT_MODEL_COMMAND = "codex exec -m gpt-5.4 --skip-git-repo-check --cd ."


@dataclass(slots=True)
class RecommendationRunResult:
    run_id: int
    snapshot_id: int | None
    recommendation: AdvisorRecommendation
    db_path: str
    reused_existing_issue: bool = False

    def to_dict(self) -> JsonObject:
        return {
            "run_id": self.run_id,
            "snapshot_id": self.snapshot_id,
            "db_path": self.db_path,
            "recommendation": self.recommendation.to_dict(),
            "reused_existing_issue": self.reused_existing_issue,
        }


class AdvisorSidecarService:
    """Operationally isolated recommendation-engine service.

    The class name is retained for compatibility while the architecture terminology
    shifts from "advisor sidecar" to "recommendation engine".
    """

    def __init__(
        self,
        *,
        repo_root: Path | None = None,
        store: AdvisorStore | None = None,
        history_store: HistoryStore | None = None,
    ) -> None:
        self.repo_root = repo_root or Path.cwd()
        self.store = store or AdvisorStore()
        self._history_store = history_store

    def _history(self) -> HistoryStore:
        if self._history_store is None:
            self._history_store = HistoryStore()
        return self._history_store

    def capture_source_snapshot(self, *, include_market: bool = True) -> JsonObject:
        from src.core.errors import ConfigError
        from src.schwab_client.cli.context import get_cached_market_client, get_client
        from src.schwab_client.snapshot import collect_snapshot

        client = get_client()
        market_client = None
        market_error: JsonObject | None = None
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
        if market_error is not None:
            snapshot.setdefault("errors", []).append(market_error)

        history = self._history().store_snapshot(snapshot, source_command="advisor-recommend")
        snapshot["history"] = history
        return snapshot

    def load_snapshot_by_id(self, snapshot_id: int) -> JsonObject:
        snapshot = self._history().get_snapshot_payload(snapshot_id)
        if snapshot is None:
            raise ValueError(f"Snapshot {snapshot_id} not found")

        payload = dict(snapshot)
        history = as_json_object(payload.get("history")) or {}
        payload["history"] = {
            "snapshot_id": snapshot_id,
            "db_path": str(self._history().path),
            **history,
        }
        return payload

    def capture_context_model(self, *, include_lynch: bool = True) -> PortfolioContext:
        from src.core.errors import ConfigError
        from src.schwab_client.cli.context import get_cached_market_client, get_client

        client = get_client()
        market_client = None
        market_error: str | None = None
        try:
            market_client = get_cached_market_client()
        except ConfigError as exc:
            market_error = f"market_auth: {exc}"

        context = PortfolioContext.assemble(
            client,
            market_client=market_client,
            include_lynch=include_lynch,
        )
        if market_error is not None:
            context.errors.append(market_error)
        return context

    def capture_context(self, *, include_lynch: bool = True) -> JsonObject:
        return self.capture_context_model(include_lynch=include_lynch).to_dict()

    def current_snapshot_provenance(
        self, context: PortfolioContext
    ) -> tuple[int | None, str | None]:
        history = as_json_object(context.history)
        snapshot_id = history.get("snapshot_id")
        db_path = history.get("db_path")
        return (
            int(snapshot_id) if isinstance(snapshot_id, int | float) else None,
            str(db_path) if db_path is not None else None,
        )

    def _extract_baseline_price(self, recommendation: AdvisorRecommendation) -> float | None:
        if recommendation.target_type != "symbol":
            return None

        from src.core.errors import PortfolioError
        from src.schwab_client.cli.context import get_client

        symbol = recommendation.target_id.upper()
        try:
            payload = get_client().get_quote(symbol)
            quote_root = as_json_object(payload.get(symbol)) or as_json_object(
                payload.get(symbol.lower())
            )
            quote = as_json_object(quote_root.get("quote"))
            last_price = quote.get("lastPrice") or quote.get("closePrice") or quote.get("mark")
            if last_price is None:
                return None
            return float(last_price)
        except (PortfolioError, OSError, TypeError, ValueError, AttributeError, KeyError):
            return None

    def _resolve_model_command(self, model_command: str | None = None) -> str:
        return model_command or os.getenv(ADVISOR_MODEL_COMMAND_ENV_VAR) or DEFAULT_MODEL_COMMAND

    def generate_structured_recommendation(
        self,
        prompt: str,
        *,
        model_command: str | None = None,
    ) -> tuple[JsonObject, str]:
        command = self._resolve_model_command(model_command)
        result = subprocess.run(
            shlex.split(command),
            cwd=self.repo_root,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr or result.stdout)

        raw = result.stdout
        stripped = raw.strip()
        candidate = stripped
        if not stripped.startswith("{"):
            start = stripped.find("{")
            end = stripped.rfind("}") + 1
            if start < 0 or end <= start:
                raise ValueError("Model did not return JSON")
            candidate = stripped[start:end]

        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Model did not return valid JSON: {exc}") from exc

        if not isinstance(payload, dict):
            raise ValueError("Model must return a JSON object")
        return payload, raw

    def _decision_context_from_snapshot(
        self,
        snapshot: JsonObject,
        *,
        supplemental_context: PortfolioContext | None = None,
    ) -> tuple[PortfolioContext | None, str | None]:
        supplemental_payload = (
            supplemental_context.to_dict() if supplemental_context is not None else None
        )
        ytd_distributions = (
            supplemental_context.ytd_distributions if supplemental_context is not None else None
        )
        return PortfolioContext.from_snapshot_payload(
            snapshot,
            ytd_distributions=ytd_distributions,
            supplemental=supplemental_payload,
        )

    def _derive_issue_key(self, recommendation: AdvisorRecommendation) -> str | None:
        target_id = (
            (recommendation.target_id or recommendation.target_type or "portfolio").strip().lower()
        )
        normalized_target = "_".join(
            part for part in __import__("re").sub(r"[^a-z0-9]+", " ", target_id).split() if part
        )
        if not normalized_target:
            return None
        return ":".join(
            [
                recommendation.recommendation_type.lower(),
                recommendation.target_type.lower(),
                normalized_target,
                recommendation.direction.lower(),
            ]
        )

    def _derive_novelty_hash(
        self, recommendation: AdvisorRecommendation, context: PortfolioContext
    ) -> str:
        import hashlib

        payload = {
            "issue_key": self._derive_issue_key(recommendation),
            "target_id": recommendation.target_id,
            "direction": recommendation.direction,
            "regime": context.regime.regime if context.regime is not None else None,
            "policy_alerts": [
                {
                    "bucket": alert.bucket,
                    "severity": alert.severity,
                    "message": alert.message,
                }
                for alert in (context.policy_delta.alerts if context.policy_delta else [])[:5]
            ],
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]

    def _derive_why_now_class(
        self, recommendation: AdvisorRecommendation, context: PortfolioContext
    ) -> str:
        target = recommendation.target_id.lower()
        alerts = context.policy_delta.alerts if context.policy_delta else []
        if any(target in str(alert.bucket or "").lower() for alert in alerts):
            return "policy_alert"
        if context.regime is not None:
            return "market_regime"
        if context.polymarket is not None:
            return "macro_signal"
        return "standing_issue"

    def recommend_from_decision_context(
        self,
        context: PortfolioContext,
        *,
        model_command: str | None = None,
    ) -> RecommendationRunResult:
        self.store.initialize()

        prompt_block = context.to_prompt_block()
        prompt = RECOMMEND_PROMPT.replace("{context}", prompt_block)
        parsed, raw = self.generate_structured_recommendation(prompt, model_command=model_command)
        rec = AdvisorRecommendation.from_dict(parsed)

        snapshot_id, db_path = self.current_snapshot_provenance(context)
        issue_key = self._derive_issue_key(rec)
        existing_open = self.store.find_open_run_by_issue_key(issue_key) if issue_key else None
        if existing_open is not None:
            existing_payload = existing_open.get("parsed_response_json") or rec.to_dict()
            existing_rec = AdvisorRecommendation.from_dict(existing_payload)
            return RecommendationRunResult(
                run_id=int(existing_open["id"]),
                snapshot_id=snapshot_id,
                recommendation=existing_rec,
                db_path=str(self.store.db_path),
                reused_existing_issue=True,
            )

        baseline_price = self._extract_baseline_price(rec)
        resolved_model_command = self._resolve_model_command(model_command)
        run_id = self.store.insert_recommendation_run(
            assembled_at=context.assembled_at,
            source_snapshot_id=snapshot_id,
            source_history_db_path=db_path,
            recommendation_type=rec.recommendation_type,
            thesis=rec.thesis,
            rationale=rec.rationale,
            target_type=rec.target_type,
            target_id=rec.target_id,
            direction=rec.direction,
            horizon_days=rec.horizon_days,
            benchmark_symbol=rec.benchmark_symbol,
            baseline_price=baseline_price,
            baseline_state_json=context.to_dict(),
            market_regime=context.regime.regime if context.regime is not None else None,
            vix_value=context.vix.vix if context.vix is not None else None,
            confidence=rec.confidence,
            tags_json=rec.tags or [],
            raw_prompt=prompt,
            raw_response=raw,
            parsed_response_json=rec.to_dict(),
            market_available=context.market_available,
            manual_accounts_included=context.manual_accounts_included,
            model_command=resolved_model_command,
            issue_key=issue_key,
            novelty_hash=self._derive_novelty_hash(rec, context),
            prompt_version="recommend-v1",
            why_now_class=self._derive_why_now_class(rec, context),
            supersedes_run_id=None,
            status="open",
        )
        return RecommendationRunResult(
            run_id=run_id,
            snapshot_id=snapshot_id,
            recommendation=rec,
            db_path=str(self.store.db_path),
            reused_existing_issue=False,
        )

    def recommend_from_context(
        self,
        context: PortfolioContext | JsonObject,
        *,
        model_command: str | None = None,
    ) -> RecommendationRunResult:
        context_model = (
            context
            if isinstance(context, PortfolioContext)
            else PortfolioContext.from_dict(context)
        )
        return self.recommend_from_decision_context(
            context_model,
            model_command=model_command,
        )

    def recommend(
        self,
        *,
        model_command: str | None = None,
        reuse_snapshot_id: int | None = None,
    ) -> RecommendationRunResult:
        self.store.initialize()
        snapshot = (
            self.load_snapshot_by_id(reuse_snapshot_id)
            if reuse_snapshot_id is not None
            else self.capture_source_snapshot()
        )
        supplemental_context = self.capture_context_model(include_lynch=True)
        context, _ = self._decision_context_from_snapshot(
            snapshot,
            supplemental_context=supplemental_context,
        )
        if context is None:
            raise ValueError("Could not build advisor context from captured snapshot")
        return self.recommend_from_decision_context(context, model_command=model_command)

    def _parse_run_created_at(self, run: JsonObject) -> datetime:
        created_at = str(run.get("created_at") or "")
        try:
            return datetime.fromisoformat(created_at)
        except ValueError:
            return datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")

    def _ready_at(self, run: JsonObject) -> datetime:
        created_at = self._parse_run_created_at(run)
        horizon_days = int(run.get("horizon_days") or 0)
        return created_at + timedelta(days=max(horizon_days, 0))

    def _latest_feedback(self, run: JsonObject) -> tuple[str | None, str | None]:
        feedback = as_json_array(run.get("feedback"))
        if not feedback:
            return None, None
        latest = feedback[0]
        if not isinstance(latest, dict):
            return None, None
        status = latest.get("status")
        notes = latest.get("notes")
        return (
            str(status) if status is not None else None,
            str(notes) if notes is not None else None,
        )

    def _before_context(
        self,
        run: JsonObject,
        history_store: HistoryStore,
    ) -> tuple[PortfolioContext | None, str | None]:
        baseline_payload = (
            run.get("baseline_state_json")
            if isinstance(run.get("baseline_state_json"), dict)
            else None
        )
        baseline_context = (
            PortfolioContext.from_dict(baseline_payload) if baseline_payload is not None else None
        )
        source_snapshot_id = run.get("source_snapshot_id")
        if source_snapshot_id is not None:
            snapshot = history_store.get_snapshot_payload(int(source_snapshot_id))
            if snapshot is not None:
                context, reason = self._decision_context_from_snapshot(
                    snapshot,
                    supplemental_context=baseline_context,
                )
                if context is not None and reason is None:
                    return context, None
                if baseline_context is not None:
                    return baseline_context, None
                return context, reason

        if baseline_context is not None:
            return baseline_context, None
        return None, "missing_baseline_context"

    def _record_ignored_evaluation(
        self,
        *,
        run: JsonObject,
        feedback_status: str,
        feedback_notes: str | None,
    ) -> JsonObject:
        notes = "Recommendation ignored by operator; no causal evaluation was recorded."
        if feedback_notes:
            notes = f"{notes} Feedback note: {feedback_notes}"
        self.store.insert_evaluation(
            run["id"],
            evaluation_snapshot_id=None,
            horizon_days=int(run.get("horizon_days") or 0),
            price_then=run.get("baseline_price"),
            price_now=None,
            benchmark_then=None,
            benchmark_now=None,
            absolute_return=None,
            benchmark_return=None,
            excess_return=None,
            policy_score_before=None,
            policy_score_after=None,
            delta_score=None,
            feedback_status=feedback_status,
            outcome="insufficient_data",
            notes=notes,
        )
        return {
            "run_id": run["id"],
            "target": run.get("target_id"),
            "horizon_days": int(run.get("horizon_days") or 0),
            "evaluation_snapshot_id": None,
            "policy_score_before": None,
            "policy_score_after": None,
            "delta_score": None,
            "feedback_status": feedback_status,
            "outcome": "insufficient_data",
            "notes": notes,
        }

    def evaluate_open_runs(self) -> JsonObject:
        self.store.initialize()
        history_store = self._history()
        evaluated: list[JsonObject] = []
        skipped: list[JsonObject] = []

        for row in self.store.list_open_runs():
            run = self.store.get_run(row["id"])
            if not run:
                continue

            feedback_status, feedback_notes = self._latest_feedback(run)
            if feedback_status == "ignored":
                evaluated.append(
                    self._record_ignored_evaluation(
                        run=run,
                        feedback_status=feedback_status,
                        feedback_notes=feedback_notes,
                    )
                )
                continue

            ready_at = self._ready_at(run)
            if ready_at > datetime.now():
                skipped.append(
                    {
                        "run_id": run["id"],
                        "reason": f"horizon_not_reached_until:{ready_at.isoformat()}",
                    }
                )
                continue

            candidate = history_store.find_first_run_on_or_after(
                ready_at.isoformat(),
                exclude_snapshot_id=(
                    int(run["source_snapshot_id"])
                    if run.get("source_snapshot_id") is not None
                    else None
                ),
            )
            if candidate is None:
                skipped.append({"run_id": run["id"], "reason": "no_later_snapshot"})
                continue

            before_context, before_reason = self._before_context(run, history_store)
            after_snapshot = history_store.get_snapshot_payload(int(candidate["snapshot_id"]))
            after_context, after_reason = (
                self._decision_context_from_snapshot(after_snapshot)
                if after_snapshot is not None
                else (None, "missing_evaluation_snapshot")
            )
            if before_context is None:
                skipped.append(
                    {
                        "run_id": run["id"],
                        "reason": before_reason or "missing_baseline_context",
                    }
                )
                continue
            if after_reason is not None:
                skipped.append({"run_id": run["id"], "reason": after_reason})
                continue

            before_score = compute_policy_health_score(before_context)
            after_score = compute_policy_health_score(after_context)
            delta_score = None
            outcome = "insufficient_data"
            notes = "Could not compute policy-health score from source and evaluation snapshots."

            if before_score is not None and after_score is not None:
                delta_score, outcome = classify_outcome(before_score, after_score)
                notes = (
                    f"Policy health score {before_score:.1f} → {after_score:.1f} "
                    f"using snapshot #{candidate['snapshot_id']}."
                )

            if feedback_status:
                notes = f"Feedback status: {feedback_status}. {notes}"
                if feedback_notes:
                    notes = f"{notes} Feedback note: {feedback_notes}"

            self.store.insert_evaluation(
                run["id"],
                evaluation_snapshot_id=int(candidate["snapshot_id"]),
                horizon_days=int(run.get("horizon_days") or 0),
                price_then=run.get("baseline_price"),
                price_now=None,
                benchmark_then=None,
                benchmark_now=None,
                absolute_return=None,
                benchmark_return=None,
                excess_return=None,
                policy_score_before=before_score,
                policy_score_after=after_score,
                delta_score=delta_score,
                feedback_status=feedback_status,
                outcome=outcome,
                notes=notes,
            )
            evaluated.append(
                {
                    "run_id": run["id"],
                    "target": run.get("target_id"),
                    "horizon_days": int(run.get("horizon_days") or 0),
                    "evaluation_snapshot_id": int(candidate["snapshot_id"]),
                    "policy_score_before": before_score,
                    "policy_score_after": after_score,
                    "delta_score": delta_score,
                    "feedback_status": feedback_status,
                    "outcome": outcome,
                    "notes": notes,
                }
            )

        return {"evaluated": evaluated, "skipped": skipped}
