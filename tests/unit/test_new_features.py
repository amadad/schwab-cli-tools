"""Tests for new features: market regime, Lynch signals, quality score,
extended order types, account scrubbing, and CLI routing."""

from unittest.mock import MagicMock, patch

import pytest

# =============================================================================
# 1. Market Regime Detection
# =============================================================================


class TestCumulativeReturn:
    """Tests for _cumulative_return helper."""

    def test_basic_return_positive(self):
        from src.core.market_service import _cumulative_return

        # 11 candles → enough for 10 days
        candles = [{"close": 100.0 + i} for i in range(11)]
        result = _cumulative_return(candles, 10)
        # (110 - 100) / 100 * 100 = 10.0%
        assert result == pytest.approx(10.0)

    def test_basic_return_negative(self):
        from src.core.market_service import _cumulative_return

        candles = [{"close": 110.0 - i} for i in range(11)]
        result = _cumulative_return(candles, 10)
        # (100 - 110) / 110 * 100 ≈ -9.09%
        assert result == pytest.approx(-9.090909, rel=1e-3)

    def test_not_enough_candles_returns_zero(self):
        from src.core.market_service import _cumulative_return

        candles = [{"close": 100.0}, {"close": 105.0}]
        result = _cumulative_return(candles, 10)
        assert result == 0.0

    def test_zero_start_price_returns_zero(self):
        from src.core.market_service import _cumulative_return

        candles = [{"close": 0.0}] + [{"close": 100.0}] * 10
        result = _cumulative_return(candles, 10)
        assert result == 0.0

    def test_flat_returns_zero(self):
        from src.core.market_service import _cumulative_return

        candles = [{"close": 50.0}] * 12
        result = _cumulative_return(candles, 10)
        assert result == 0.0


class TestGetMarketRegime:
    """Tests for get_market_regime with mocked client."""

    def _make_candles(self, start: float, change: float, count: int = 80):
        """Build candle list with linear price change."""
        step = change / count
        return [{"close": start + step * i} for i in range(count)]

    def _mock_client(self, agg_change, bil_change, tlt_change):
        """Create a mock client that returns price history for AGG, BIL, TLT."""
        client = MagicMock()

        def price_history(symbol):
            candle_map = {
                "AGG": self._make_candles(100, agg_change),
                "BIL": self._make_candles(100, bil_change),
                "TLT": self._make_candles(100, tlt_change),
            }
            resp = MagicMock()
            resp.json.return_value = {"candles": candle_map.get(symbol, [])}
            return resp

        client.get_price_history_every_day = price_history
        return client

    def test_risk_on_when_agg_beats_bil(self):
        from src.core.market_service import get_market_regime

        # AGG gaining more than BIL over 60 days → risk_on
        client = self._mock_client(agg_change=5, bil_change=1, tlt_change=2)
        result = get_market_regime(client)

        assert result["regime"] == "risk_on"
        assert result["risk_on"] is True

    def test_risk_off_rising_rates(self):
        from src.core.market_service import get_market_regime

        # AGG losing to BIL, and TLT losing to BIL → rising rates
        client = self._mock_client(agg_change=-2, bil_change=1, tlt_change=-3)
        result = get_market_regime(client)

        assert result["regime"] == "risk_off_rising_rates"
        assert result["risk_on"] is False
        assert result["rates_rising"] is True

    def test_risk_off_falling_rates(self):
        from src.core.market_service import get_market_regime

        # AGG losing to BIL, but TLT beating BIL → falling rates
        client = self._mock_client(agg_change=-2, bil_change=1, tlt_change=5)
        result = get_market_regime(client)

        assert result["regime"] == "risk_off_falling_rates"
        assert result["risk_on"] is False
        assert result["rates_rising"] is False

    def test_result_has_expected_keys(self):
        from src.core.market_service import get_market_regime

        client = self._mock_client(agg_change=5, bil_change=1, tlt_change=2)
        result = get_market_regime(client)

        assert "regime" in result
        assert "description" in result
        assert "signals" in result
        assert "risk_on" in result
        assert "rates_rising" in result
        assert "timestamp" in result

        signals = result["signals"]
        for key in ("agg_60d_return", "bil_60d_return", "tlt_20d_return", "bil_20d_return"):
            assert key in signals


# =============================================================================
# 2. Lynch Sell Signals
# =============================================================================


class TestClassifyCompanyType:
    """Tests for classify_company_type."""

    def test_fast_grower(self):
        from src.core.lynch_service import classify_company_type

        result = classify_company_type({"epsTTMGrowthRate5Y": 25, "peRatio": 30})
        assert result == "fast_grower"

    def test_slow_grower(self):
        from src.core.lynch_service import classify_company_type

        result = classify_company_type(
            {
                "epsTTMGrowthRate5Y": 3,
                "peRatio": 8,
                "dividendYield": 4,
            }
        )
        assert result == "slow_grower"

    def test_stalwart(self):
        from src.core.lynch_service import classify_company_type

        result = classify_company_type({"epsTTMGrowthRate5Y": 15, "peRatio": 20})
        assert result == "stalwart"

    def test_turnaround_negative_pe(self):
        from src.core.lynch_service import classify_company_type

        result = classify_company_type({"epsTTMGrowthRate5Y": 5, "peRatio": -5})
        assert result == "turnaround"

    def test_turnaround_zero_pe(self):
        from src.core.lynch_service import classify_company_type

        result = classify_company_type({"epsTTMGrowthRate5Y": 5, "peRatio": 0})
        assert result == "turnaround"

    def test_missing_data_defaults(self):
        from src.core.lynch_service import classify_company_type

        # All None/missing → pe=0 → turnaround
        result = classify_company_type({})
        assert result == "turnaround"


class TestCheckSellSignals:
    """Tests for check_sell_signals per company type."""

    def test_stalwart_pe_above_growth(self):
        from src.core.lynch_service import check_sell_signals

        signals = check_sell_signals(
            "stalwart",
            {
                "peRatio": 40,
                "epsTTMGrowthRate5Y": 10,
            },
        )
        assert len(signals) >= 1
        assert any("P/E well above" in s["trigger"] for s in signals)

    def test_stalwart_no_signal_when_pe_reasonable(self):
        from src.core.lynch_service import check_sell_signals

        signals = check_sell_signals(
            "stalwart",
            {
                "peRatio": 15,
                "epsTTMGrowthRate5Y": 12,
            },
        )
        pe_signals = [s for s in signals if "P/E" in s["trigger"]]
        assert len(pe_signals) == 0

    def test_fast_grower_peg_above_one(self):
        from src.core.lynch_service import check_sell_signals

        signals = check_sell_signals(
            "fast_grower",
            {
                "peRatio": 30,
                "epsTTMGrowthRate5Y": 20,
            },
        )
        assert any("PEG > 1" in s["trigger"] for s in signals)

    def test_slow_grower_high_payout(self):
        from src.core.lynch_service import check_sell_signals

        signals = check_sell_signals(
            "slow_grower",
            {
                "dividendPayoutRatio": 75,
            },
        )
        assert any("payout ratio" in s["trigger"].lower() for s in signals)

    def test_turnaround_near_52week_high(self):
        from src.core.lynch_service import check_sell_signals

        signals = check_sell_signals(
            "turnaround",
            {
                "high52": 100,
                "low52": 50,
                "lastPrice": 95,
            },
        )
        assert any("turnaround" in s["trigger"].lower() for s in signals)

    def test_universal_at_52week_high(self):
        from src.core.lynch_service import check_sell_signals

        signals = check_sell_signals(
            "stalwart",
            {
                "peRatio": 15,
                "epsTTMGrowthRate5Y": 12,
                "high52": 100,
                "low52": 50,
                "lastPrice": 99,
            },
        )
        assert any("52-week high" in s["trigger"] for s in signals)

    def test_no_signals_on_empty_fundamentals(self):
        from src.core.lynch_service import check_sell_signals

        signals = check_sell_signals("stalwart", {})
        assert signals == []


class TestAnalyzeHoldingsLynch:
    """Tests for analyze_holdings_lynch."""

    def test_analyzes_multiple_holdings(self):
        from src.core.lynch_service import analyze_holdings_lynch

        holdings = [
            {
                "symbol": "AAPL",
                "fundamentals": {"epsTTMGrowthRate5Y": 15, "peRatio": 25},
            },
            {
                "symbol": "T",
                "fundamentals": {"epsTTMGrowthRate5Y": 2, "peRatio": 8, "dividendYield": 5},
            },
        ]
        results = analyze_holdings_lynch(holdings)

        assert len(results) == 2
        assert results[0]["symbol"] == "AAPL"
        assert results[1]["symbol"] == "T"
        assert "company_type" in results[0]
        assert "signals" in results[0]

    def test_empty_list(self):
        from src.core.lynch_service import analyze_holdings_lynch

        results = analyze_holdings_lynch([])
        assert results == []

    def test_missing_fundamentals_key(self):
        from src.core.lynch_service import analyze_holdings_lynch

        results = analyze_holdings_lynch([{"symbol": "XYZ"}])
        assert len(results) == 1
        assert results[0]["symbol"] == "XYZ"
        assert results[0]["company_type"] == "turnaround"  # defaults


# =============================================================================
# 3. Quality Score
# =============================================================================


class TestScoreFromFundamentals:
    """Tests for score_from_fundamentals."""

    def test_good_fundamentals_passes(self):
        from src.core.score_service import score_from_fundamentals

        fund = {
            "peRatio": 18,
            "epsTTMGrowthRate5Y": 20,
            "revenueGrowthRate5Y": 18,
            "netProfitMarginTTM": 30,
            "returnOnEquity": 30,
            "returnOnInvestment": 25,
            "dividendYield": 1.5,
            "dividendPayoutRatio": 25,
            "totalDebtToEquity": 0.2,
            "marketCap": 500_000_000_000,
            "beta": 1.0,
        }
        result = score_from_fundamentals("AAPL", fund)

        assert result["symbol"] == "AAPL"
        assert result["signal"] == "PASS"
        assert result["projected_total"] >= 60

    def test_poor_fundamentals_sells(self):
        from src.core.score_service import score_from_fundamentals

        fund = {
            "peRatio": 80,
            "epsTTMGrowthRate5Y": -5,
            "revenueGrowthRate5Y": -3,
            "netProfitMarginTTM": 2,
            "returnOnEquity": 2,
            "returnOnInvestment": 1,
            "dividendYield": 0,
            "dividendPayoutRatio": 0,
            "totalDebtToEquity": 5.0,
            "marketCap": 100_000_000,
            "beta": 2.0,
        }
        result = score_from_fundamentals("JUNK", fund)

        assert result["signal"] == "SELL"
        assert result["projected_total"] < 45

    def test_missing_data_handled_gracefully(self):
        from src.core.score_service import score_from_fundamentals

        result = score_from_fundamentals("EMPTY", {})

        assert result["symbol"] == "EMPTY"
        assert "signal" in result
        assert result["signal"] in ("PASS", "WATCH", "SELL")
        assert "dimensions" in result
        # Should have all 15 dimensions
        assert len(result["dimensions"]) == 15

    def test_result_structure(self):
        from src.core.score_service import score_from_fundamentals

        result = score_from_fundamentals("TEST", {"peRatio": 20})

        for key in (
            "symbol",
            "dimensions",
            "quantitative_total",
            "quantitative_max",
            "scored_count",
            "unscored_count",
            "projected_total",
            "signal",
        ):
            assert key in result

        # Qualitative dimensions should have score=None
        assert result["dimensions"]["business_model"]["score"] is None
        # Quantitative dimensions should have numeric score
        assert isinstance(result["dimensions"]["valuation"]["score"], int)


# =============================================================================
# 4. Extended Order Types
# =============================================================================


class TestBuildEquityOrder:
    """Tests for _build_equity_order with STOP, STOP_LIMIT, TRAILING_STOP."""

    @pytest.fixture
    def wrapper(self):
        from src.schwab_client.client import SchwabClientWrapper

        mock_raw = MagicMock()
        return SchwabClientWrapper(mock_raw)

    def test_stop_order(self, wrapper):
        order = wrapper._build_equity_order(
            action="SELL",
            order_type="STOP",
            symbol="AAPL",
            quantity=10,
            stop_price=150.0,
        )

        assert order["orderType"] == "STOP"
        assert order["stopPrice"] == "150.0"
        assert order["orderStrategyType"] == "SINGLE"
        assert order["session"] == "NORMAL"
        assert order["duration"] == "GOOD_TILL_CANCEL"

        leg = order["orderLegCollection"][0]
        assert leg["instruction"] == "SELL"
        assert leg["quantity"] == 10
        assert leg["instrument"]["symbol"] == "AAPL"
        assert leg["instrument"]["assetType"] == "EQUITY"

    def test_stop_limit_order(self, wrapper):
        order = wrapper._build_equity_order(
            action="SELL",
            order_type="STOP_LIMIT",
            symbol="MSFT",
            quantity=5,
            stop_price=300.0,
            limit_price=295.0,
        )

        assert order["orderType"] == "STOP_LIMIT"
        assert order["stopPrice"] == "300.0"
        assert order["price"] == "295.0"

        leg = order["orderLegCollection"][0]
        assert leg["instruction"] == "SELL"
        assert leg["quantity"] == 5
        assert leg["instrument"]["symbol"] == "MSFT"

    def test_trailing_stop_order(self, wrapper):
        order = wrapper._build_equity_order(
            action="SELL",
            order_type="TRAILING_STOP",
            symbol="TSLA",
            quantity=20,
            trailing_stop_percent=5.0,
        )

        assert order["orderType"] == "TRAILING_STOP"
        assert order["stopPriceLinkBasis"] == "MARK"
        assert order["stopPriceLinkType"] == "PERCENT"
        assert order["stopPriceOffset"] == "5.0"

        leg = order["orderLegCollection"][0]
        assert leg["instruction"] == "SELL"
        assert leg["quantity"] == 20
        assert leg["instrument"]["symbol"] == "TSLA"

    def test_market_order_uses_schwab_builder(self, wrapper):
        order = wrapper._build_equity_order(
            action="BUY",
            order_type="MARKET",
            symbol="aapl",
            quantity=10,
        )
        # schwab-py builders produce an OrderBuilder; .build() returns a dict
        assert isinstance(order, dict)

    def test_symbol_uppercased(self, wrapper):
        order = wrapper._build_equity_order(
            action="SELL",
            order_type="STOP",
            symbol="aapl",
            quantity=1,
            stop_price=100.0,
        )
        assert order["orderLegCollection"][0]["instrument"]["symbol"] == "AAPL"

    def test_buy_stop_order(self, wrapper):
        order = wrapper._build_equity_order(
            action="BUY",
            order_type="STOP",
            symbol="GOOG",
            quantity=3,
            stop_price=180.0,
        )
        assert order["orderType"] == "STOP"
        assert order["orderLegCollection"][0]["instruction"] == "BUY"


# =============================================================================
# 5. Account Scrubbing
# =============================================================================


class TestScrubAccountIdentifiers:
    """Tests for scrub_account_identifiers in output.py."""

    @patch("src.schwab_client.cli.output.secure_config")
    def test_replaces_account_numbers_in_string(self, mock_config):
        from src.schwab_client.cli.output import scrub_account_identifiers

        mock_config.account_mappings = {"acct_trading": "12345678"}

        result = scrub_account_identifiers("Account 12345678 balance")
        assert "12345678" not in result
        assert "[acct_trading]" in result

    @patch("src.schwab_client.cli.output.secure_config")
    def test_scrubs_nested_dict(self, mock_config):
        from src.schwab_client.cli.output import scrub_account_identifiers

        mock_config.account_mappings = {"acct_trading": "12345678"}

        data = {
            "account": "12345678",
            "details": {"number": "12345678", "value": 1000},
        }
        result = scrub_account_identifiers(data)

        assert "12345678" not in result["account"]
        assert "12345678" not in result["details"]["number"]
        assert result["details"]["value"] == 1000

    @patch("src.schwab_client.cli.output.secure_config")
    def test_scrubs_nested_list(self, mock_config):
        from src.schwab_client.cli.output import scrub_account_identifiers

        mock_config.account_mappings = {"acct_roth": "87654321"}

        data = ["Account: 87654321", {"num": "87654321"}]
        result = scrub_account_identifiers(data)

        assert "87654321" not in result[0]
        assert "87654321" not in result[1]["num"]
        assert "[acct_roth]" in result[0]

    @patch("src.schwab_client.cli.output.secure_config")
    def test_no_accounts_is_noop(self, mock_config):
        from src.schwab_client.cli.output import scrub_account_identifiers

        mock_config.account_mappings = {}

        data = {"account": "12345678", "value": 1000}
        result = scrub_account_identifiers(data)

        assert result == data

    @patch("src.schwab_client.cli.output.secure_config")
    def test_non_string_values_unchanged(self, mock_config):
        from src.schwab_client.cli.output import scrub_account_identifiers

        mock_config.account_mappings = {"acct": "12345678"}

        data = {"count": 42, "flag": True, "empty": None}
        result = scrub_account_identifiers(data)

        assert result["count"] == 42
        assert result["flag"] is True
        assert result["empty"] is None

    @patch("src.schwab_client.cli.output.secure_config")
    def test_multiple_accounts_scrubbed(self, mock_config):
        from src.schwab_client.cli.output import scrub_account_identifiers

        mock_config.account_mappings = {
            "acct_trading": "11111111",
            "acct_roth": "22222222",
        }

        data = "Accounts: 11111111 and 22222222"
        result = scrub_account_identifiers(data)

        assert "11111111" not in result
        assert "22222222" not in result
        assert "[acct_trading]" in result
        assert "[acct_roth]" in result


# =============================================================================
# 6. CLI Routing for New Commands
# =============================================================================


class TestCLIRoutingNewCommands:
    """Tests for CLI routing of regime, lynch, score, and sell --stop."""

    @patch("src.schwab_client.cli.cmd_regime")
    def test_regime_json_routes(self, mock_cmd):
        from src.schwab_client.cli import main

        main(["regime", "--json"])
        mock_cmd.assert_called_once_with(output_mode="json")

    @patch("src.schwab_client.cli.cmd_lynch")
    def test_lynch_json_routes(self, mock_cmd):
        from src.schwab_client.cli import main

        main(["lynch", "--json"])
        mock_cmd.assert_called_once_with(output_mode="json")

    @patch("src.schwab_client.cli.cmd_score")
    def test_score_json_routes(self, mock_cmd):
        from src.schwab_client.cli import main

        main(["score", "AAPL", "--json"])
        mock_cmd.assert_called_once_with("AAPL", output_mode="json")

    @patch("src.schwab_client.cli.cmd_sell")
    def test_sell_with_stop_parses(self, mock_cmd):
        from src.schwab_client.cli import main

        main(["sell", "AAPL", "10", "--stop", "150", "--dry-run"])

        mock_cmd.assert_called_once()
        call_kwargs = mock_cmd.call_args
        # positional args[0] is the args list
        assert call_kwargs[0][0] == ["AAPL", "10"]
        assert call_kwargs[1]["stop_price"] == 150.0
        assert call_kwargs[1]["dry_run"] is True

    @patch("src.schwab_client.cli.cmd_sell")
    def test_sell_with_trailing_stop_parses(self, mock_cmd):
        from src.schwab_client.cli import main

        main(["sell", "AAPL", "10", "--trailing-stop", "5", "--dry-run"])

        mock_cmd.assert_called_once()
        call_kwargs = mock_cmd.call_args
        assert call_kwargs[1]["trailing_stop_percent"] == 5.0
        assert call_kwargs[1]["dry_run"] is True

    @patch("src.schwab_client.cli.cmd_regime")
    def test_regime_alias_routes(self, mock_cmd):
        from src.schwab_client.cli import main

        main(["reg", "--json"])
        mock_cmd.assert_called_once_with(output_mode="json")

    @patch("src.schwab_client.cli.cmd_lynch")
    def test_lynch_alias_routes(self, mock_cmd):
        from src.schwab_client.cli import main

        main(["ly", "--json"])
        mock_cmd.assert_called_once_with(output_mode="json")
