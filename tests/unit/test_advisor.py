"""Tests for the portfolio advisor learning loop."""

from unittest.mock import patch

import pytest

from src.core.advisor import (
    build_learning_prompt,
    compute_pattern_stats,
    enrich_thesis_trajectory,
    evaluate_open_theses,
    record_thesis_with_context,
)
from src.schwab_client._history.advisor_store import AdvisorStore


@pytest.fixture
def advisor_store(tmp_path):
    """Create a fresh AdvisorStore in a temp directory."""
    db_path = tmp_path / "test_advisor.db"
    return AdvisorStore(path=db_path)


class TestThesisRecording:
    def test_record_basic_thesis(self, advisor_store):
        result = advisor_store.record_thesis(
            symbol="AAPL",
            rationale="Strong iPhone cycle",
            time_horizon_days=90,
            entry_price=180.0,
        )
        assert result["thesis_id"] is not None
        assert result["symbol"] == "AAPL"

    def test_record_thesis_with_context(self, advisor_store):
        result = record_thesis_with_context(
            advisor_store,
            symbol="MSFT",
            rationale="Cloud growth acceleration",
            entry_price=400.0,
            market_context={
                "regime": "risk_on",
                "vix": 15.5,
                "sentiment": "favorable",
                "sector_rotation": "risk_on",
            },
        )
        assert result["symbol"] == "MSFT"

        thesis = advisor_store.get_thesis(result["thesis_id"])
        assert thesis["regime_at_entry"] == "risk_on"
        assert thesis["vix_at_entry"] == 15.5
        assert thesis["sentiment_at_entry"] == "favorable"

    def test_record_thesis_auto_price(self, advisor_store):
        """Test that entry price is auto-fetched when not provided."""
        with patch("src.core.price_data.get_current_price", return_value=185.50):
            result = record_thesis_with_context(
                advisor_store,
                symbol="AAPL",
                rationale="Test auto price",
            )
            assert result.get("entry_price") == 185.50

    def test_record_thesis_with_tags(self, advisor_store):
        result = advisor_store.record_thesis(
            symbol="NVDA",
            rationale="AI compute demand",
            tags=["ai", "semiconductor", "growth"],
        )
        thesis = advisor_store.get_thesis(result["thesis_id"])
        assert thesis["tags"] == "ai,semiconductor,growth"

    def test_list_theses_by_status(self, advisor_store):
        advisor_store.record_thesis(symbol="AAPL", rationale="test1")
        advisor_store.record_thesis(symbol="MSFT", rationale="test2")
        result = advisor_store.record_thesis(symbol="GOOG", rationale="test3")
        advisor_store.close_thesis(result["thesis_id"])

        open_theses = advisor_store.list_theses(status="open")
        assert len(open_theses) == 2

        closed_theses = advisor_store.list_theses(status="closed")
        assert len(closed_theses) == 1
        assert closed_theses[0]["symbol"] == "GOOG"

    def test_list_theses_all(self, advisor_store):
        advisor_store.record_thesis(symbol="AAPL", rationale="test1")
        result = advisor_store.record_thesis(symbol="MSFT", rationale="test2")
        advisor_store.close_thesis(result["thesis_id"])

        all_theses = advisor_store.list_theses(status=None)
        assert len(all_theses) == 2


class TestThesisEvaluation:
    def test_evaluate_with_prices(self, advisor_store):
        advisor_store.record_thesis(
            symbol="AAPL",
            rationale="test",
            entry_price=100.0,
            time_horizon_days=90,
        )

        with patch("src.core.price_data.compute_benchmark_return", return_value=5.0):
            with patch("src.core.price_data.get_prices_bulk", return_value={}):
                results = evaluate_open_theses(
                    advisor_store,
                    price_lookup={"AAPL": 115.0},
                )

        assert len(results) == 1
        assert results[0]["return_pct"] == 15.0
        assert results[0]["benchmark_return_pct"] == 5.0
        assert results[0]["alpha_pct"] == 10.0

    def test_evaluate_target_hit(self, advisor_store):
        advisor_store.record_thesis(
            symbol="AAPL",
            rationale="test",
            entry_price=100.0,
            target_return_pct=10.0,
        )

        with patch("src.core.price_data.compute_benchmark_return", return_value=None):
            with patch("src.core.price_data.get_prices_bulk", return_value={}):
                results = evaluate_open_theses(
                    advisor_store,
                    price_lookup={"AAPL": 112.0},
                )

        assert "TARGET_HIT" in results[0]["flags"]
        assert results[0].get("auto_closed") == "target_hit"

    def test_evaluate_stop_hit(self, advisor_store):
        advisor_store.record_thesis(
            symbol="AAPL",
            rationale="test",
            entry_price=100.0,
            stop_loss_pct=10.0,
        )

        with patch("src.core.price_data.compute_benchmark_return", return_value=None):
            with patch("src.core.price_data.get_prices_bulk", return_value={}):
                results = evaluate_open_theses(
                    advisor_store,
                    price_lookup={"AAPL": 88.0},
                )

        assert "STOP_HIT" in results[0]["flags"]
        assert results[0].get("auto_closed") == "stop_hit"

    def test_evaluate_yfinance_fallback(self, advisor_store):
        """When no price_lookup given, falls back to yfinance."""
        advisor_store.record_thesis(
            symbol="AAPL",
            rationale="test",
            entry_price=100.0,
        )

        with patch("src.core.price_data.get_prices_bulk", return_value={"AAPL": 110.0}):
            with patch("src.core.price_data.compute_benchmark_return", return_value=None):
                results = evaluate_open_theses(advisor_store)

        assert len(results) == 1
        assert results[0]["return_pct"] == 10.0

    def test_evaluate_regime_shift(self, advisor_store):
        advisor_store.record_thesis(
            symbol="AAPL",
            rationale="test",
            entry_price=100.0,
            regime="risk_on",
        )

        with patch("src.core.price_data.compute_benchmark_return", return_value=None):
            with patch("src.core.price_data.get_prices_bulk", return_value={}):
                results = evaluate_open_theses(
                    advisor_store,
                    price_lookup={"AAPL": 95.0},
                    market_context={"regime": "risk_off"},
                )

        assert "REGIME_SHIFTED" in results[0]["flags"]

    def test_evaluate_no_open_theses(self, advisor_store):
        results = evaluate_open_theses(advisor_store)
        assert results == []

    def test_evaluate_short_direction(self, advisor_store):
        advisor_store.record_thesis(
            symbol="TSLA",
            direction="short",
            rationale="overvalued",
            entry_price=200.0,
        )

        with patch("src.core.price_data.compute_benchmark_return", return_value=None):
            with patch("src.core.price_data.get_prices_bulk", return_value={}):
                results = evaluate_open_theses(
                    advisor_store,
                    price_lookup={"TSLA": 180.0},
                )

        # Short: profit when price drops
        assert results[0]["return_pct"] == 10.0


class TestCheckpoints:
    def test_record_and_get_checkpoints(self, advisor_store):
        thesis = advisor_store.record_thesis(symbol="AAPL", rationale="test")
        tid = thesis["thesis_id"]

        advisor_store.record_checkpoint(tid, current_price=105.0, return_pct=5.0)
        advisor_store.record_checkpoint(tid, current_price=110.0, return_pct=10.0)

        checkpoints = advisor_store.get_checkpoints(tid)
        assert len(checkpoints) == 2
        assert checkpoints[0]["return_pct"] == 10.0  # Most recent first


class TestReviews:
    def test_record_and_get_review(self, advisor_store):
        thesis = advisor_store.record_thesis(symbol="AAPL", rationale="test")
        tid = thesis["thesis_id"]

        advisor_store.record_review(
            tid,
            final_return_pct=12.5,
            was_correct=True,
            what_worked="Bought during low VIX, regime was risk-on",
            lessons="Low VIX + risk_on = good entry for growth",
        )

        review = advisor_store.get_review(tid)
        assert review is not None
        assert review["final_return_pct"] == 12.5
        assert review["was_correct"] == 1
        assert "Low VIX" in review["lessons"]

    def test_review_upsert(self, advisor_store):
        thesis = advisor_store.record_thesis(symbol="AAPL", rationale="test")
        tid = thesis["thesis_id"]

        advisor_store.record_review(tid, final_return_pct=5.0, was_correct=True)
        advisor_store.record_review(tid, final_return_pct=8.0, was_correct=True)

        review = advisor_store.get_review(tid)
        assert review["final_return_pct"] == 8.0  # Updated


class TestPatterns:
    def test_compute_patterns_empty(self, advisor_store):
        with patch("src.core.price_data.compute_benchmark_return", return_value=None):
            patterns = compute_pattern_stats(advisor_store)
        assert patterns == []

    def test_compute_patterns_from_reviews(self, advisor_store):
        for regime, ret, correct in [
            ("risk_on", 15.0, True),
            ("risk_on", 8.0, True),
            ("risk_off", -5.0, False),
        ]:
            t = advisor_store.record_thesis(
                symbol="AAPL",
                rationale="test",
                regime=regime,
                vix=18.0,
            )
            advisor_store.close_thesis(t["thesis_id"])
            advisor_store.record_review(
                t["thesis_id"],
                final_return_pct=ret,
                was_correct=correct,
            )

        with patch("src.core.price_data.compute_benchmark_return", return_value=5.0):
            patterns = compute_pattern_stats(advisor_store)

        assert len(patterns) > 0

        all_patterns = advisor_store.get_patterns()
        pattern_names = [p["pattern_name"] for p in all_patterns]
        assert any("regime:" in name for name in pattern_names)

    def test_upsert_pattern(self, advisor_store):
        advisor_store.upsert_pattern(
            pattern_name="test_pattern",
            conditions={"regime": "risk_on"},
            sample_size=5,
            hit_rate=0.8,
            avg_return_pct=10.0,
        )

        patterns = advisor_store.get_patterns()
        assert len(patterns) == 1
        assert patterns[0]["hit_rate"] == 0.8


class TestPerformanceSummary:
    def test_empty_summary(self, advisor_store):
        perf = advisor_store.get_performance_summary()
        assert perf["total_theses"] == 0
        assert perf["win_rate"] is None

    def test_summary_with_reviews(self, advisor_store):
        for correct in [True, True, False]:
            t = advisor_store.record_thesis(symbol="AAPL", rationale="test")
            advisor_store.close_thesis(t["thesis_id"])
            advisor_store.record_review(
                t["thesis_id"],
                final_return_pct=10.0 if correct else -5.0,
                was_correct=correct,
            )

        perf = advisor_store.get_performance_summary()
        assert perf["total_theses"] == 3
        assert perf["reviewed"] == 3
        assert perf["win_rate"] == pytest.approx(2 / 3)


class TestThesisWithHistory:
    def test_get_thesis_with_history(self, advisor_store):
        t = advisor_store.record_thesis(
            symbol="AAPL",
            rationale="test",
            entry_price=100.0,
        )
        tid = t["thesis_id"]

        advisor_store.record_checkpoint(tid, current_price=105.0, return_pct=5.0)
        advisor_store.record_review(
            tid,
            final_return_pct=12.0,
            was_correct=True,
            lessons="Good entry",
        )

        thesis = advisor_store.get_thesis_with_history(tid)
        assert thesis is not None
        assert len(thesis["checkpoints"]) == 1
        assert thesis["review"]["final_return_pct"] == 12.0


class TestLearningPrompt:
    def test_build_empty(self, advisor_store):
        prompt = build_learning_prompt(advisor_store)
        assert "## Advisor Learning Loop Context" in prompt
        assert "Total theses: 0" in prompt

    def test_build_with_data(self, advisor_store):
        t = advisor_store.record_thesis(
            symbol="AAPL",
            rationale="test",
            entry_price=100.0,
            regime="risk_on",
        )
        advisor_store.close_thesis(t["thesis_id"])
        advisor_store.record_review(
            t["thesis_id"],
            final_return_pct=10.0,
            was_correct=True,
            lessons="Buy in risk-on",
        )

        prompt = build_learning_prompt(advisor_store)
        assert "AAPL" in prompt
        assert "Buy in risk-on" in prompt


class TestResearchScans:
    def test_record_and_get_scans(self, advisor_store):
        result = advisor_store.record_scan(
            scan_name="growth_scan",
            regime="risk_on",
            criteria={"sector": "technology", "pe_ratio": "<30"},
            candidates=[
                {"symbol": "AAPL", "score": 85},
                {"symbol": "MSFT", "score": 90},
            ],
            patterns_used=["regime:risk_on"],
        )
        assert result["candidate_count"] == 2

        scans = advisor_store.get_recent_scans()
        assert len(scans) == 1
        assert scans[0]["candidate_count"] == 2


class TestEnrichTrajectory:
    def test_enrich_trajectory(self, advisor_store):
        t = advisor_store.record_thesis(
            symbol="AAPL",
            rationale="test",
            entry_price=100.0,
        )

        mock_trajectory = {
            "symbol": "AAPL",
            "entry_price": 100.0,
            "current_price": 115.0,
            "return_pct": 15.0,
            "max_drawdown_pct": -5.0,
            "max_gain_pct": 18.0,
            "peak_trough_drawdown_pct": -8.0,
            "trading_days": 60,
            "path": [],
        }

        with patch("src.core.price_data.compute_price_trajectory", return_value=mock_trajectory):
            with patch("src.core.price_data.compute_benchmark_return", return_value=8.0):
                trajectory = enrich_thesis_trajectory(advisor_store, t["thesis_id"])

        assert trajectory is not None
        assert trajectory["return_pct"] == 15.0
        assert trajectory["benchmark_return_pct"] == 8.0
        assert trajectory["alpha_pct"] == 7.0

    def test_enrich_trajectory_missing_thesis(self, advisor_store):
        result = enrich_thesis_trajectory(advisor_store, 9999)
        assert result is None
