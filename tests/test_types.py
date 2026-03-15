"""Tests for core types and fee calculations."""

from engine.core.types import (
    Action,
    EngineConfig,
    Fill,
    InventoryState,
    Mode,
    Orderbook,
    OrderbookLevel,
    OrderRequest,
    Quote,
    Side,
    maker_fee_cents,
    taker_fee_cents,
)


class TestFeeCalculation:
    def test_taker_fee_at_50_cents(self):
        # 10 contracts at 50 cents: ceil(0.07 * 10 * 0.50 * 0.50) = ceil(0.175) = 1
        assert taker_fee_cents(10, 50) == 1

    def test_taker_fee_at_50_cents_100_contracts(self):
        # 100 contracts at 50 cents: ceil(0.07 * 100 * 0.50 * 0.50) = ceil(1.75) = 2
        assert taker_fee_cents(100, 50) == 2

    def test_maker_fee_at_50_cents(self):
        # 10 contracts at 50 cents: ceil(0.0175 * 10 * 0.50 * 0.50) = ceil(0.04375) = 1
        assert maker_fee_cents(10, 50) == 1

    def test_maker_fee_at_50_cents_100_contracts(self):
        # 100 contracts at 50 cents: ceil(0.0175 * 100 * 0.50 * 0.50) = ceil(0.4375) = 1
        assert maker_fee_cents(100, 50) == 1

    def test_fee_at_extreme_low(self):
        # At price = 1 cent: P*(1-P) = 0.01 * 0.99 = 0.0099, very low fee
        assert taker_fee_cents(1, 1) == 1  # ceil(0.07 * 1 * 0.01 * 0.99) = ceil(0.000693) = 1

    def test_fee_at_extreme_high(self):
        # At price = 99 cents: same as 1 cent (symmetric)
        assert taker_fee_cents(1, 99) == 1

    def test_maker_cheaper_than_taker(self):
        for price in [10, 25, 50, 75, 90]:
            assert maker_fee_cents(10, price) <= taker_fee_cents(10, price)


class TestOrderbook:
    def test_mid_price(self):
        book = Orderbook(
            ticker="TEST",
            yes_bids=[OrderbookLevel(48, 100)],
            yes_asks=[OrderbookLevel(52, 100)],
        )
        assert book.mid_price_cents() == 50.0

    def test_spread(self):
        book = Orderbook(
            ticker="TEST",
            yes_bids=[OrderbookLevel(48, 100)],
            yes_asks=[OrderbookLevel(52, 100)],
        )
        assert book.spread_cents() == 4

    def test_empty_book_defaults(self):
        book = Orderbook(ticker="TEST")
        assert book.mid_price_cents() == 50.0
        assert book.spread_cents() == 99
        assert book.best_bid() is None
        assert book.best_ask() is None

    def test_best_bid_ask(self):
        book = Orderbook(
            ticker="TEST",
            yes_bids=[OrderbookLevel(45, 50), OrderbookLevel(44, 100)],
            yes_asks=[OrderbookLevel(55, 50), OrderbookLevel(56, 100)],
        )
        assert book.best_bid() == 45
        assert book.best_ask() == 55


class TestInventoryState:
    def test_long_position(self):
        inv = InventoryState(ticker="TEST", net_position=5)
        assert inv.is_long
        assert not inv.is_short
        assert not inv.is_flat

    def test_short_position(self):
        inv = InventoryState(ticker="TEST", net_position=-3)
        assert inv.is_short
        assert not inv.is_long

    def test_flat_position(self):
        inv = InventoryState(ticker="TEST", net_position=0)
        assert inv.is_flat


class TestOrderRequest:
    def test_notional(self):
        req = OrderRequest(
            ticker="TEST", side=Side.YES, action=Action.BUY,
            count=10, price_cents=50,
        )
        assert req.notional_cents == 500


class TestEngineConfig:
    def test_demo_urls(self):
        config = EngineConfig(kalshi_env="demo")
        assert "demo-api.kalshi.co" in config.kalshi_base_url
        assert "demo-api.kalshi.co" in config.kalshi_ws_url

    def test_production_urls(self):
        config = EngineConfig(kalshi_env="production")
        assert "api.elections.kalshi.com" in config.kalshi_base_url
        assert "api.elections.kalshi.com" in config.kalshi_ws_url
