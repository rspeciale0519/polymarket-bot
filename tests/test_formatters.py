"""Tests for notification formatters."""

from engine.core.types import Action, Fill, InventoryState, Side
from engine.notifications.formatters import (
    format_dollars,
    format_fill,
    format_pnl,
    format_positions,
    format_risk_summary,
)


class TestFormatPnl:
    def test_positive(self):
        assert format_pnl(150) == "+$1.50"

    def test_negative(self):
        assert format_pnl(-250) == "-$2.50"

    def test_zero(self):
        assert format_pnl(0) == "+$0.00"


class TestFormatDollars:
    def test_normal(self):
        assert format_dollars(5000) == "$50.00"

    def test_small(self):
        assert format_dollars(1) == "$0.01"


class TestFormatFill:
    def test_buy_fill(self):
        fill = Fill(
            fill_id="f1", order_id="o1", ticker="TEST",
            side=Side.YES, action=Action.BUY, count=5,
            price_cents=50, fee_cents=1, is_maker=True,
        )
        text = format_fill(fill)
        assert "BUY" in text
        assert "5x" in text
        assert "TEST" in text
        assert "Maker" in text

    def test_fill_with_pnl(self):
        fill = Fill(
            fill_id="f1", order_id="o1", ticker="TEST",
            side=Side.YES, action=Action.SELL, count=3,
            price_cents=60, fee_cents=1, is_maker=True,
            pnl_cents=30,
        )
        text = format_fill(fill)
        assert "P&L" in text
        assert "+$0.30" in text


class TestFormatPositions:
    def test_empty(self):
        assert format_positions([]) == "No open positions"

    def test_with_positions(self):
        positions = [
            InventoryState(ticker="MKT-A", net_position=5,
                           unrealized_pnl_cents=100, realized_pnl_cents=50),
            InventoryState(ticker="MKT-B", net_position=-3,
                           unrealized_pnl_cents=-20, realized_pnl_cents=10),
        ]
        text = format_positions(positions)
        assert "MKT-A" in text
        assert "LONG" in text
        assert "MKT-B" in text
        assert "SHORT" in text
        assert "Total" in text


class TestFormatRiskSummary:
    def test_normal(self):
        summary = {
            "halted": False,
            "daily_pnl_cents": -50,
            "daily_limit_cents": 500,
            "total_exposure_cents": 2000,
            "exposure_limit_cents": 5000,
            "active_positions": 2,
            "max_position_per_market": 10,
        }
        text = format_risk_summary(summary)
        assert "OK" in text
        assert "Positions: 2" in text
