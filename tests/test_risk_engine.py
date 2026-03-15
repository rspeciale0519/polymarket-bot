"""Tests for the risk engine."""

from engine.core.types import (
    Action,
    EngineConfig,
    InventoryState,
    OrderRequest,
    Side,
)
from engine.risk.risk_engine import RiskEngine


def _make_config(**overrides) -> EngineConfig:
    defaults = {
        "max_position_per_market": 10,
        "global_exposure_limit_cents": 5000,
        "daily_loss_limit_cents": 500,
    }
    defaults.update(overrides)
    return EngineConfig(**defaults)


def _buy_request(ticker: str = "TEST", count: int = 5, price: int = 50) -> OrderRequest:
    return OrderRequest(ticker=ticker, side=Side.YES, action=Action.BUY,
                        count=count, price_cents=price)


class TestRiskChecks:
    def test_approve_normal_order(self):
        risk = RiskEngine(_make_config())
        violations = risk.check(_buy_request())
        assert violations == []

    def test_block_over_inventory_cap(self):
        risk = RiskEngine(_make_config(max_position_per_market=5))
        risk.update_position(InventoryState(ticker="TEST", net_position=4))
        violations = risk.check(_buy_request(count=3))
        blocked = [v for v in violations if v.severity == "block"]
        assert len(blocked) == 1
        assert "inventory" in blocked[0].rule

    def test_allow_at_inventory_cap(self):
        risk = RiskEngine(_make_config(max_position_per_market=10))
        risk.update_position(InventoryState(ticker="TEST", net_position=5))
        violations = risk.check(_buy_request(count=5))
        blocked = [v for v in violations if v.severity == "block"]
        assert len(blocked) == 0

    def test_block_over_global_exposure(self):
        risk = RiskEngine(_make_config(global_exposure_limit_cents=200))
        violations = risk.check(_buy_request(count=5, price=50))
        # 5 * 50 = 250 > 200
        blocked = [v for v in violations if v.severity == "block"]
        assert len(blocked) == 1
        assert "global_exposure" in blocked[0].rule

    def test_halt_on_daily_loss(self):
        risk = RiskEngine(_make_config(daily_loss_limit_cents=100))
        risk.add_realized_pnl(-150)
        violations = risk.check(_buy_request())
        halt = [v for v in violations if v.severity == "halt"]
        assert len(halt) == 1
        assert "daily_loss" in halt[0].rule

    def test_halt_when_engine_halted(self):
        risk = RiskEngine(_make_config())
        risk.halt("test reason")
        violations = risk.check(_buy_request())
        assert len(violations) == 1
        assert violations[0].severity == "halt"

    def test_resume_after_halt(self):
        risk = RiskEngine(_make_config())
        risk.halt("test")
        assert risk.is_halted
        risk.resume()
        assert not risk.is_halted
        violations = risk.check(_buy_request())
        assert violations == []

    def test_daily_pnl_tracking(self):
        risk = RiskEngine(_make_config())
        risk.add_realized_pnl(-50)
        risk.add_realized_pnl(30)
        assert risk.daily_realized_pnl_cents == -20

    def test_risk_summary(self):
        risk = RiskEngine(_make_config())
        risk.update_position(InventoryState(ticker="A", net_position=3))
        summary = risk.get_risk_summary()
        assert summary["active_positions"] == 1
        assert summary["halted"] is False
