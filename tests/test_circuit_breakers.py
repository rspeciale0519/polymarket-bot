"""Tests for circuit breakers."""

import pytest

from engine.core.event_bus import EventBus
from engine.core.types import EngineConfig
from engine.risk.circuit_breakers import (
    CircuitBreakerManager,
    CircuitBreakerState,
    RapidLossDetector,
    ToxicityDetector,
)
from engine.risk.risk_engine import RiskEngine


class TestRapidLossDetector:
    def test_no_trip_below_threshold(self):
        detector = RapidLossDetector(min_losses=3)
        detector.record_fill(-10)
        detector.record_fill(-10)
        assert not detector.is_tripped

    def test_trip_at_threshold(self):
        detector = RapidLossDetector(min_losses=3)
        detector.record_fill(-10)
        detector.record_fill(-10)
        tripped = detector.record_fill(-10)
        assert tripped
        assert detector.is_tripped

    def test_reset_clears(self):
        detector = RapidLossDetector(min_losses=2)
        detector.record_fill(-10)
        detector.record_fill(-10)
        assert detector.is_tripped
        detector.reset()
        assert not detector.is_tripped
        assert detector.loss_count == 0

    def test_ignores_winning_fills(self):
        detector = RapidLossDetector(min_losses=3)
        detector.record_fill(10)
        detector.record_fill(20)
        detector.record_fill(30)
        assert not detector.is_tripped

    def test_total_loss(self):
        detector = RapidLossDetector(min_losses=5)
        detector.record_fill(-10)
        detector.record_fill(-20)
        assert detector.total_loss_cents == -30


class TestToxicityDetector:
    def test_low_toxicity(self):
        detector = ToxicityDetector(window_size=10)
        for _ in range(10):
            detector.record_fill(False)
        assert detector.score == 0.0
        assert not detector.should_widen_spreads
        assert not detector.should_pull_quotes

    def test_high_toxicity_widens(self):
        detector = ToxicityDetector(window_size=10)
        for _ in range(8):
            detector.record_fill(True)
        for _ in range(2):
            detector.record_fill(False)
        assert detector.score == 80.0
        assert detector.should_widen_spreads
        assert not detector.should_pull_quotes

    def test_critical_toxicity_pulls(self):
        detector = ToxicityDetector(window_size=10)
        for _ in range(9):
            detector.record_fill(True)
        for _ in range(1):
            detector.record_fill(False)
        assert detector.score == 90.0
        assert detector.should_pull_quotes

    def test_reset(self):
        detector = ToxicityDetector(window_size=10)
        for _ in range(10):
            detector.record_fill(True)
        detector.reset()
        assert detector.score == 0.0


class TestCircuitBreakerManager:
    def test_get_status_all_ok(self):
        bus = EventBus()
        risk = RiskEngine(EngineConfig())
        mgr = CircuitBreakerManager(bus=bus, risk_engine=risk)
        statuses = mgr.get_status()
        assert all(s.state == CircuitBreakerState.OK for s in statuses)

    def test_spread_multiplier_normal(self):
        bus = EventBus()
        risk = RiskEngine(EngineConfig())
        mgr = CircuitBreakerManager(bus=bus, risk_engine=risk)
        assert mgr.spread_multiplier == 1.0

    def test_spread_multiplier_widen(self):
        bus = EventBus()
        risk = RiskEngine(EngineConfig())
        mgr = CircuitBreakerManager(bus=bus, risk_engine=risk)
        for _ in range(15):
            mgr.record_toxicity(True)
        for _ in range(5):
            mgr.record_toxicity(False)
        assert mgr.spread_multiplier == 2.0

    def test_reset_all(self):
        bus = EventBus()
        risk = RiskEngine(EngineConfig())
        risk.halt("test")
        mgr = CircuitBreakerManager(bus=bus, risk_engine=risk)
        mgr.reset_all()
        assert not risk.is_halted
