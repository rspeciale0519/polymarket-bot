"""Tests for orderbook state management."""

from engine.core.types import Orderbook, OrderbookLevel
from engine.market_data.orderbook import OrderbookManager


class TestOrderbookManager:
    def test_get_or_create(self):
        mgr = OrderbookManager()
        book = mgr.get_or_create("TEST-TICKER")
        assert book.ticker == "TEST-TICKER"
        assert mgr.get("TEST-TICKER") is book

    def test_remove(self):
        mgr = OrderbookManager()
        mgr.get_or_create("TEST")
        mgr.remove("TEST")
        assert mgr.get("TEST") is None

    def test_active_tickers(self):
        mgr = OrderbookManager()
        mgr.get_or_create("A")
        mgr.get_or_create("B")
        assert sorted(mgr.active_tickers) == ["A", "B"]


class TestApplySnapshot:
    def test_basic_snapshot(self):
        mgr = OrderbookManager()
        msg = {
            "orderbook_fp": {
                "yes_dollars": [["0.4800", "100.00"], ["0.4700", "50.00"]],
                "no_dollars": [["0.4800", "200.00"], ["0.4700", "75.00"]],
            }
        }
        book = mgr.apply_snapshot("TEST", msg)

        # YES bids: 48, 47
        assert book.yes_bids[0].price_cents == 48
        assert book.yes_bids[0].quantity == 100
        assert book.yes_bids[1].price_cents == 47

        # YES asks derived from NO bids: 100-48=52, 100-47=53
        assert book.yes_asks[0].price_cents == 52
        assert book.yes_asks[0].quantity == 200
        assert book.yes_asks[1].price_cents == 53

    def test_snapshot_mid_price(self):
        mgr = OrderbookManager()
        msg = {
            "orderbook_fp": {
                "yes_dollars": [["0.4500", "100.00"]],
                "no_dollars": [["0.4500", "100.00"]],
            }
        }
        book = mgr.apply_snapshot("TEST", msg)
        # YES bid = 45, NO bid = 45 → YES ask = 55
        assert book.mid_price_cents() == 50.0
        assert book.spread_cents() == 10

    def test_snapshot_replaces_previous(self):
        mgr = OrderbookManager()
        msg1 = {
            "orderbook_fp": {
                "yes_dollars": [["0.3000", "50.00"]],
                "no_dollars": [["0.3000", "50.00"]],
            }
        }
        mgr.apply_snapshot("TEST", msg1)

        msg2 = {
            "orderbook_fp": {
                "yes_dollars": [["0.5000", "100.00"]],
                "no_dollars": [["0.5000", "100.00"]],
            }
        }
        book = mgr.apply_snapshot("TEST", msg2)
        assert book.yes_bids[0].price_cents == 50
        assert len(book.yes_bids) == 1


class TestApplyDelta:
    def test_delta_updates_levels(self):
        mgr = OrderbookManager()
        # Initial snapshot
        mgr.apply_snapshot("TEST", {
            "orderbook_fp": {
                "yes_dollars": [["0.4800", "100.00"]],
                "no_dollars": [["0.4800", "100.00"]],
            }
        })

        # Delta: add new YES bid at 47
        delta = {
            "msg": {
                "yes_dollars": [["0.4700", "50.00"]],
                "no_dollars": [],
            }
        }
        book = mgr.apply_delta("TEST", delta)
        assert book is not None
        assert len(book.yes_bids) == 2
        assert book.yes_bids[0].price_cents == 48  # sorted desc
        assert book.yes_bids[1].price_cents == 47

    def test_delta_removes_level(self):
        mgr = OrderbookManager()
        mgr.apply_snapshot("TEST", {
            "orderbook_fp": {
                "yes_dollars": [["0.4800", "100.00"], ["0.4700", "50.00"]],
                "no_dollars": [],
            }
        })

        # Remove level at 48 (quantity = 0)
        delta = {
            "msg": {
                "yes_dollars": [["0.4800", "0.00"]],
                "no_dollars": [],
            }
        }
        book = mgr.apply_delta("TEST", delta)
        assert len(book.yes_bids) == 1
        assert book.yes_bids[0].price_cents == 47

    def test_delta_on_nonexistent_book_returns_none(self):
        mgr = OrderbookManager()
        result = mgr.apply_delta("NOPE", {"msg": {"yes_dollars": [], "no_dollars": []}})
        assert result is None
