"""Minimal advisor recommendation journal and evaluator."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.core.advisor_models import AdvisorRecommendation
from src.core.advisor_prompts import RECOMMEND_PROMPT
from src.core.advisor_scoring import classify_outcome, compute_policy_health_score
from src.core.context import PortfolioContext
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "snapshot_id": self.snapshot_id,
            "db_path": self.db_path,
            "recommendation": self.recommendation.to_dict(),
            "reused_existing_issue": self.reused_existing_issue,
        }


class AdvisorSidecarService:
    def __init__(self, *, repo_root: Path | None = None, store: AdvisorStore | None = None) -> None:
        self.repo_root = repo_root or Path.cwd()
        self.store = store or AdvisorStore()
        self._last_context_payload: dict[str, Any] | None = None

    def capture_source_snapshot(self, *, include_market: bool = True) -> dict[str, Any]:
        cmd = ["uv", "run", "schwab", "snapshot", "--json"]
        if not include_market:
            cmd.append("--no-market")
        result = subprocess.run(
            cmd,
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            timeout=240,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr or result.stdout)
        envelope = json.loads(result.stdout)
        data = envelope.get("data", envelope)
        if isinstance(data, dict) and isinstance(data.get("snapshot"), dict):
            return data["snapshot"]
        return data

    def load_snapshot_by_id(self, snapshot_id: int) -> dict[str, Any]:
        result = subprocess.run(
            ["uv", "run", "schwab", "history", "--snapshot-id", str(snapshot_id), "--json"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr or result.stdout)
        envelope = json.loads(result.stdout)
        data = envelope.get("data", envelope)
        snapshot = data.get("snapshot") if isinstance(data, dict) else None
        if not isinstance(snapshot, dict):
            snapshot = data if isinstance(data, dict) else {}
        if not isinstance(snapshot.get("history"), dict):
            snapshot = dict(snapshot)
            snapshot["history"] = {
                "snapshot_id": data.get("snapshot_id", snapshot_id),
                "db_path": data.get("db_path"),
            }
        return snapshot

    def capture_context(self, *, include_lynch: bool = True) -> dict[str, Any]:
        cmd = ["uv", "run", "schwab", "context", "--json"]
        if include_lynch:
            cmd.append("--lynch")
        result = subprocess.run(
            cmd,
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr or result.stdout)
        envelope = json.loads(result.stdout)
        payload = envelope.get("data", envelope)
        self._last_context_payload = payload
        return payload

    def render_context_prompt(self) -> str:
        if self._last_context_payload is not None:
            context = PortfolioContext.from_dict(self._last_context_payload)
            return context.to_prompt_block()

        result = subprocess.run(
            ["uv", "run", "schwab", "context", "--prompt"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr or result.stdout)
        return result.stdout.strip()

    def current_snapshot_provenance(self, context: dict[str, Any]) -> tuple[int | None, str | None]:
        history = context.get("history") or {}
        return history.get("snapshot_id"), history.get("db_path")

    def _extract_baseline_price(self, recommendation: AdvisorRecommendation) -> float | None:
        if recommendation.target_type != "symbol":
            return None
        sym = recommendation.target_id
        result = subprocess.run(
            ["uv", "run", "schwab", "fundamentals", sym, "--json"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            return None
        try:
            envelope = json.loads(result.stdout)
            data = envelope.get("data", envelope)
            return float(data.get("lastPrice")) if data.get("lastPrice") is not None else None
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    def _resolve_model_command(self, model_command: str | None = None) -> str:
        return model_command or os.getenv(ADVISOR_MODEL_COMMAND_ENV_VAR) or DEFAULT_MODEL_COMMAND

    def generate_structured_recommendation(
        self,
        prompt: str,
        *,
        model_command: str | None = None,
    ) -> tuple[dict[str, Any], str]:
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

    def _context_from_snapshot(
        self,
        snapshot: dict[str, Any],
        *,
        ytd_distributions: dict[str, Any] | None = None,
        supplemental: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str | None]:
        context, reason = PortfolioContext.from_snapshot_payload(
            snapshot,
            ytd_distributions=ytd_distributions,
            supplemental=supplemental,
        )
        return context.to_dict(), reason

    def _derive_issue_key(self, recommendation: AdvisorRecommendation) -> str | None:
        target_id = (recommendation.target_id or recommendation.target_type or "portfolio").strip().lower()
        normalized_target = "_".join(part for part in __import__("re").sub(r"[^a-z0-9]+", " ", target_id).split() if part)
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

    def _derive_novelty_hash(self, recommendation: AdvisorRecommendation, context: dict[str, Any]) -> str:
        import hashlib

        payload = {
            "issue_key": self._derive_issue_key(recommendation),
            "target_id": recommendation.target_id,
            "direction": recommendation.direction,
            "regime": (context.get("regime") or {}).get("regime"),
            "policy_alerts": [
                {
                    "bucket": alert.get("bucket"),
                    "severity": alert.get("severity"),
                    "message": alert.get("message"),
                }
                for alert in ((context.get("policy_delta") or {}).get("alerts") or [])[:5]
            ],
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]

    def _derive_why_now_class(self, recommendation: AdvisorRecommendation, context: dict[str, Any]) -> str:
        target = recommendation.target_id.lower()
        alerts = ((context.get("policy_delta") or {}).get("alerts") or [])
        if any(target in str(alert.get("bucket") or "").lower() for alert in alerts):
            return "policy_alert"
        if context.get("regime"):
            return "market_regime"
        if context.get("polymarket"):
            return "macro_signal"
        return "standing_issue"

    def recommend_from_context(
        self,
        context: dict[str, Any],
        *,
        model_command: str | None = None,
    ) -> RecommendationRunResult:
        self.store.initialize()
        self._last_context_payload = context

        prompt_block = PortfolioContext.from_dict(context).to_prompt_block()
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
            assembled_at=context.get("assembled_at"),
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
            baseline_state_json=context,
            market_regime=(context.get("regime") or {}).get("regime"),
            vix_value=(context.get("vix") or {}).get("vix"),
            confidence=rec.confidence,
            tags_json=rec.tags or [],
            raw_prompt=prompt,
            raw_response=raw,
            parsed_response_json=rec.to_dict(),
            market_available=context.get("market_available", False),
            manual_accounts_included=context.get("manual_accounts_included", False),
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
        supplemental_context = self.capture_context(include_lynch=True)
        context, _ = self._context_from_snapshot(
            snapshot,
            ytd_distributions=supplemental_context.get("ytd_distributions"),
            supplemental=supplemental_context,
        )
        if context is None:
            raise ValueError("Could not build advisor context from captured snapshot")
        return self.recommend_from_context(context, model_command=model_command)

    def _parse_run_created_at(self, run: dict[str, Any]) -> datetime:
        created_at = str(run.get("created_at") or "")
        try:
            return datetime.fromisoformat(created_at)
        except ValueError:
            return datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")

    def _ready_at(self, run: dict[str, Any]) -> datetime:
        created_at = self._parse_run_created_at(run)
        horizon_days = int(run.get("horizon_days") or 0)
        return created_at + timedelta(days=max(horizon_days, 0))

    def _latest_feedback(self, run: dict[str, Any]) -> tuple[str | None, str | None]:
        feedback = run.get("feedback") or []
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
        run: dict[str, Any],
        history_store: HistoryStore,
    ) -> tuple[dict[str, Any] | None, str | None]:
        baseline = run.get("baseline_state_json") if isinstance(run.get("baseline_state_json"), dict) else None
        source_snapshot_id = run.get("source_snapshot_id")
        if source_snapshot_id is not None:
            snapshot = history_store.get_snapshot_payload(int(source_snapshot_id))
            if snapshot is not None:
                baseline_ytd = (
                    baseline.get("ytd_distributions") if isinstance(baseline, dict) else None
                )
                context, reason = self._context_from_snapshot(
                    snapshot,
                    ytd_distributions=baseline_ytd,
                    supplemental=baseline,
                )
                if context is not None and reason is None:
                    return context, None
                if baseline is not None:
                    return baseline, None
                return context, reason

        if baseline is not None:
            return baseline, None
        return None, "missing_baseline_context"

    def _record_ignored_evaluation(
        self,
        *,
        run: dict[str, Any],
        feedback_status: str,
        feedback_notes: str | None,
    ) -> dict[str, Any]:
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

    def evaluate_open_runs(self) -> dict[str, Any]:
        self.store.initialize()
        history_store = HistoryStore()
        evaluated: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []

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
                self._context_from_snapshot(after_snapshot)
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
