"""Tests for the portfolio advisor learning loop."""

import json

import pytest

from src.core.advisor import (
    build_learning_prompt,
    compute_pattern_stats,
    evaluate_open_theses,
    record_thesis_with_context,
)
from src.schwab_client._history.advisor_store import AdvisorStore


@pytest.fixture
def advisor_store(tmp_path):
    """Create a temporary AdvisorStore for testing."""
    db_path = tmp_path / "test_advisor.db"
    return AdvisorStore(path=db_path)


class TestAdvisorStore:
    def test_record_thesis(self, advisor_store):
        result = advisor_store.record_thesis(
            symbol="AAPL",
            direction="long",
            rationale="Strong earnings momentum",
            time_horizon_days=90,
            entry_price=150.0,
            target_return_pct=15.0,
            stop_loss_pct=5.0,
            regime="risk_on",
            vix=18.5,
        )
        assert result["thesis_id"] is not None
        assert result["symbol"] == "AAPL"

    def test_get_thesis(self, advisor_store):
        result = advisor_store.record_thesis(
            symbol="MSFT", rationale="Cloud growth", entry_price=400.0,
        )
        thesis = advisor_store.get_thesis(result["thesis_id"])
        assert thesis is not None
        assert thesis["symbol"] == "MSFT"
        assert thesis["status"] == "open"
        assert thesis["entry_price"] == 400.0

    def test_list_theses_by_status(self, advisor_store):
        advisor_store.record_thesis(symbol="AAPL", rationale="Test 1")
        r2 = advisor_store.record_thesis(symbol="MSFT", rationale="Test 2")
        advisor_store.close_thesis(r2["thesis_id"], reason="target_hit")

        open_theses = advisor_store.list_theses(status="open")
        assert len(open_theses) == 1
        assert open_theses[0]["symbol"] == "AAPL"

        closed_theses = advisor_store.list_theses(status="closed")
        assert len(closed_theses) == 1
        assert closed_theses[0]["symbol"] == "MSFT"

    def test_close_thesis(self, advisor_store):
        result = advisor_store.record_thesis(symbol="GOOG", rationale="Test")
        close_result = advisor_store.close_thesis(result["thesis_id"], reason="stop_hit")
        assert close_result["status"] == "closed"

        thesis = advisor_store.get_thesis(result["thesis_id"])
        assert thesis["status"] == "closed"
        assert thesis["close_reason"] == "stop_hit"

    def test_record_checkpoint(self, advisor_store):
        thesis = advisor_store.record_thesis(symbol="AAPL", rationale="Test", entry_price=150.0)
        cp = advisor_store.record_checkpoint(
            thesis["thesis_id"],
            current_price=165.0,
            return_pct=10.0,
            regime="risk_on",
            vix=17.0,
        )
        assert cp["thesis_id"] == thesis["thesis_id"]

        checkpoints = advisor_store.get_checkpoints(thesis["thesis_id"])
        assert len(checkpoints) == 1
        assert checkpoints[0]["current_price"] == 165.0
        assert checkpoints[0]["return_pct"] == 10.0

    def test_record_review(self, advisor_store):
        thesis = advisor_store.record_thesis(symbol="AAPL", rationale="Test")
        advisor_store.close_thesis(thesis["thesis_id"])

        review = advisor_store.record_review(
            thesis["thesis_id"],
            final_return_pct=12.5,
            was_correct=True,
            what_worked="Regime alignment",
            lessons="Buy on risk_on regime transitions",
        )
        assert review["thesis_id"] == thesis["thesis_id"]

        retrieved = advisor_store.get_review(thesis["thesis_id"])
        assert retrieved is not None
        assert retrieved["final_return_pct"] == 12.5
        assert retrieved["was_correct"] == 1
        assert "Regime alignment" in retrieved["what_worked"]

    def test_upsert_pattern(self, advisor_store):
        result = advisor_store.upsert_pattern(
            pattern_name="regime:risk_on",
            conditions={"regime": "risk_on"},
            sample_size=5,
            hit_rate=0.8,
            avg_return_pct=12.3,
        )
        assert result["pattern_name"] == "regime:risk_on"

        patterns = advisor_store.get_patterns()
        assert len(patterns) == 1
        assert patterns[0]["hit_rate"] == 0.8

    def test_record_scan(self, advisor_store):
        result = advisor_store.record_scan(
            scan_name="risk_on_scan",
            regime="risk_on",
            criteria={"sector": "tech", "vix_below": 20},
            candidates=[
                {"symbol": "AAPL", "score": 85},
                {"symbol": "MSFT", "score": 82},
            ],
            patterns_used=["regime:risk_on"],
        )
        assert result["candidate_count"] == 2

        scans = advisor_store.get_recent_scans()
        assert len(scans) == 1

    def test_performance_summary_empty(self, advisor_store):
        perf = advisor_store.get_performance_summary()
        assert perf["total_theses"] == 0
        assert perf["win_rate"] is None

    def test_performance_summary_with_data(self, advisor_store):
        # Create and review some theses
        t1 = advisor_store.record_thesis(
            symbol="AAPL", rationale="Test", regime="risk_on",
        )
        t2 = advisor_store.record_thesis(
            symbol="MSFT", rationale="Test", regime="risk_off",
        )
        advisor_store.close_thesis(t1["thesis_id"])
        advisor_store.close_thesis(t2["thesis_id"])

        advisor_store.record_review(
            t1["thesis_id"], final_return_pct=15.0, was_correct=True,
        )
        advisor_store.record_review(
            t2["thesis_id"], final_return_pct=-5.0, was_correct=False,
        )

        perf = advisor_store.get_performance_summary()
        assert perf["total_theses"] == 2
        assert perf["reviewed"] == 2
        assert perf["win_rate"] == 0.5
        assert perf["avg_return_pct"] == 5.0
        assert len(perf["by_regime"]) == 2

    def test_get_thesis_with_history(self, advisor_store):
        t = advisor_store.record_thesis(symbol="AAPL", rationale="Test", entry_price=150.0)
        advisor_store.record_checkpoint(t["thesis_id"], current_price=155.0, return_pct=3.3)
        advisor_store.record_checkpoint(t["thesis_id"], current_price=160.0, return_pct=6.7)
        advisor_store.close_thesis(t["thesis_id"])
        advisor_store.record_review(t["thesis_id"], final_return_pct=6.7, was_correct=True)

        full = advisor_store.get_thesis_with_history(t["thesis_id"])
        assert full is not None
        assert len(full["checkpoints"]) == 2
        assert full["review"] is not None
        assert full["review"]["final_return_pct"] == 6.7

    def test_get_thesis_with_history_not_found(self, advisor_store):
        assert advisor_store.get_thesis_with_history(999) is None

    def test_get_learning_context(self, advisor_store):
        ctx = advisor_store.get_learning_context()
        assert "performance" in ctx
        assert "open_theses" in ctx
        assert "patterns" in ctx


class TestAdvisorService:
    def test_record_thesis_with_market_context(self, advisor_store):
        result = record_thesis_with_context(
            advisor_store,
            symbol="NVDA",
            rationale="AI demand cycle",
            entry_price=800.0,
            market_context={
                "regime": "risk_on",
                "vix": {"vix": 16.5},
                "sentiment": "favorable",
                "sector_rotation": "risk_on",
            },
        )
        assert result["symbol"] == "NVDA"

        thesis = advisor_store.get_thesis(result["thesis_id"])
        assert thesis["regime_at_entry"] == "risk_on"
        assert thesis["vix_at_entry"] == 16.5
        assert thesis["sentiment_at_entry"] == "favorable"

    def test_record_thesis_without_market_context(self, advisor_store):
        result = record_thesis_with_context(
            advisor_store,
            symbol="AAPL",
            rationale="Value play",
        )
        thesis = advisor_store.get_thesis(result["thesis_id"])
        assert thesis["regime_at_entry"] is None

    def test_evaluate_open_theses(self, advisor_store):
        advisor_store.record_thesis(
            symbol="AAPL", rationale="Test", entry_price=150.0,
            target_return_pct=10.0, stop_loss_pct=5.0,
        )
        advisor_store.record_thesis(
            symbol="MSFT", rationale="Test", entry_price=400.0,
        )

        results = evaluate_open_theses(
            advisor_store,
            price_lookup={"AAPL": 165.0, "MSFT": 410.0},
            market_context={"regime": "risk_on"},
        )
        assert len(results) == 2

        aapl = next(r for r in results if r["symbol"] == "AAPL")
        assert aapl["return_pct"] == 10.0
        assert "TARGET_HIT" in aapl["flags"]
        assert aapl.get("auto_closed") == "target_hit"

    def test_evaluate_missing_price(self, advisor_store):
        advisor_store.record_thesis(symbol="XYZ", rationale="Test", entry_price=50.0)

        results = evaluate_open_theses(
            advisor_store,
            price_lookup={},
        )
        assert len(results) == 1
        assert results[0]["status"] == "no_price"

    def test_evaluate_stop_loss_hit(self, advisor_store):
        advisor_store.record_thesis(
            symbol="AAPL", rationale="Test", entry_price=150.0,
            stop_loss_pct=5.0,
        )
        results = evaluate_open_theses(
            advisor_store,
            price_lookup={"AAPL": 140.0},
        )
        aapl = results[0]
        assert "STOP_HIT" in aapl["flags"]
        assert aapl.get("auto_closed") == "stop_hit"

    def test_evaluate_regime_shift(self, advisor_store):
        advisor_store.record_thesis(
            symbol="AAPL", rationale="Test", entry_price=150.0,
            regime="risk_on",
        )
        results = evaluate_open_theses(
            advisor_store,
            price_lookup={"AAPL": 155.0},
            market_context={"regime": "risk_off"},
        )
        assert "REGIME_SHIFTED" in results[0]["flags"]

    def test_compute_pattern_stats(self, advisor_store):
        # Create several reviewed theses to extract patterns from
        for i, (sym, regime, ret, correct) in enumerate([
            ("AAPL", "risk_on", 15.0, True),
            ("MSFT", "risk_on", 8.0, True),
            ("GOOG", "risk_on", -3.0, False),
            ("AMZN", "risk_off", -7.0, False),
            ("META", "risk_off", 2.0, True),
        ]):
            t = advisor_store.record_thesis(
                symbol=sym, rationale=f"Test {i}", regime=regime, vix=18.0,
            )
            advisor_store.close_thesis(t["thesis_id"])
            advisor_store.record_review(
                t["thesis_id"], final_return_pct=ret, was_correct=correct,
            )

        patterns = compute_pattern_stats(advisor_store)
        assert len(patterns) > 0

        all_patterns = advisor_store.get_patterns()
        regime_on = next(
            (p for p in all_patterns if p["pattern_name"] == "regime:risk_on"), None
        )
        assert regime_on is not None
        assert regime_on["sample_size"] == 3

    def test_compute_pattern_stats_empty(self, advisor_store):
        patterns = compute_pattern_stats(advisor_store)
        assert patterns == []

    def test_build_learning_prompt(self, advisor_store):
        t = advisor_store.record_thesis(
            symbol="AAPL", rationale="Test thesis", regime="risk_on",
        )
        advisor_store.close_thesis(t["thesis_id"])
        advisor_store.record_review(
            t["thesis_id"], final_return_pct=10.0, was_correct=True,
            lessons="Risk-on regime entry works well",
        )

        prompt = build_learning_prompt(advisor_store)
        assert "Advisor Learning Loop Context" in prompt
        assert "AAPL" in prompt
        assert "risk_on" in prompt

    def test_build_learning_prompt_empty(self, advisor_store):
        prompt = build_learning_prompt(advisor_store)
        assert "Advisor Learning Loop Context" in prompt
        assert "0" in prompt  # total theses = 0


class TestAdvisorPrompts:
    def test_render_advisor_prompt(self):
        from src.core.advisor_prompts import render_advisor_prompt

        for template in ["retrospective", "patterns", "scan"]:
            rendered = render_advisor_prompt(
                template,
                learning_context="test context",
                market_context="test market",
            )
            assert "test context" in rendered
            assert len(rendered) > 100

    def test_render_unknown_template(self):
        from src.core.advisor_prompts import render_advisor_prompt

        with pytest.raises(ValueError, match="Unknown advisor template"):
            render_advisor_prompt("nonexistent", learning_context="test")
