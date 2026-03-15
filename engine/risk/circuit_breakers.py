"""
Circuit breakers — stateful pattern monitors.

Each breaker watches for dangerous patterns and can trip to halt trading.
All thresholds are configurable from the dashboard.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

import structlog

from engine.core.event_bus import EventBus
from engine.core.types import (
    CircuitBreakerState,
    ConnectionLost,
    FillEvent,
)
from engine.risk.risk_engine import RiskEngine

logger = structlog.get_logger(__name__)


@dataclass
class BreakerStatus:
    name: str
    state: CircuitBreakerState = CircuitBreakerState.OK
    reason: str = ""
    tripped_at: float = 0.0


class RapidLossDetector:
    """Trips if 3+ losing fills occur within a sliding window."""

    def __init__(self, window_seconds: int = 3600, min_losses: int = 3) -> None:
        self._window = window_seconds
        self._min_losses = min_losses
        self._losses: deque[tuple[float, int]] = deque()  # (timestamp, pnl_cents)
        self._tripped = False

    def record_fill(self, pnl_cents: int) -> bool:
        """Record a fill's P&L. Returns True if breaker should trip."""
        now = time.monotonic()
        if pnl_cents < 0:
            self._losses.append((now, pnl_cents))

        self._prune(now)

        if len(self._losses) >= self._min_losses:
            self._tripped = True
            return True
        return False

    def reset(self) -> None:
        self._losses.clear()
        self._tripped = False

    @property
    def is_tripped(self) -> bool:
        self._prune(time.monotonic())
        if len(self._losses) < self._min_losses:
            self._tripped = False
        return self._tripped

    @property
    def loss_count(self) -> int:
        self._prune(time.monotonic())
        return len(self._losses)

    @property
    def total_loss_cents(self) -> int:
        self._prune(time.monotonic())
        return sum(pnl for _, pnl in self._losses)

    def _prune(self, now: float) -> None:
        cutoff = now - self._window
        while self._losses and self._losses[0][0] < cutoff:
            self._losses.popleft()


class ToxicityDetector:
    """
    Monitors adverse selection: fills where the price moves against us
    immediately after fill. Scores 0-100.
    >70: widen spreads. >85: pull all quotes.
    """

    def __init__(self, window_size: int = 20) -> None:
        self._window_size = window_size
        self._fills: deque[bool] = deque(maxlen=window_size)  # True = adverse
        self._score: float = 0.0

    def record_fill(self, was_adverse: bool) -> None:
        self._fills.append(was_adverse)
        if self._fills:
            self._score = (sum(self._fills) / len(self._fills)) * 100

    @property
    def score(self) -> float:
        return self._score

    @property
    def should_widen_spreads(self) -> bool:
        return self._score > 70

    @property
    def should_pull_quotes(self) -> bool:
        return self._score > 85

    def reset(self) -> None:
        self._fills.clear()
        self._score = 0.0


class CircuitBreakerManager:
    """Manages all circuit breakers and integrates with the risk engine."""

    def __init__(
        self,
        bus: EventBus,
        risk_engine: RiskEngine,
        rapid_loss_window_seconds: int = 3600,
        rapid_loss_min_count: int = 3,
    ) -> None:
        self._bus = bus
        self._risk = risk_engine
        self._rapid_loss = RapidLossDetector(
            window_seconds=rapid_loss_window_seconds,
            min_losses=rapid_loss_min_count,
        )
        self._toxicity = ToxicityDetector()
        self._connection_lost = False

        self._bus.subscribe(FillEvent, self._on_fill)
        self._bus.subscribe(ConnectionLost, self._on_connection_lost)

    async def _on_fill(self, event: FillEvent) -> None:
        fill = event.fill

        # Rapid loss detection
        if fill.pnl_cents < 0:
            if self._rapid_loss.record_fill(fill.pnl_cents):
                logger.warning(
                    "circuit_breaker.rapid_loss_tripped",
                    losses=self._rapid_loss.loss_count,
                    total_loss=self._rapid_loss.total_loss_cents,
                )
                self._risk.halt(
                    f"Rapid loss: {self._rapid_loss.loss_count} losing fills, "
                    f"total {self._rapid_loss.total_loss_cents}c"
                )

    async def _on_connection_lost(self, event: ConnectionLost) -> None:
        self._connection_lost = True
        logger.warning("circuit_breaker.connection_lost", reason=event.reason)
        # Risk engine halt + cancel-all is handled by main.py's event handler

    def record_toxicity(self, was_adverse: bool) -> None:
        """Called externally when we can determine if a fill was adverse."""
        self._toxicity.record_fill(was_adverse)

        if self._toxicity.should_pull_quotes:
            logger.warning(
                "circuit_breaker.toxicity_critical",
                score=self._toxicity.score,
            )
            self._risk.halt(f"Toxicity score {self._toxicity.score:.0f} > 85")
        elif self._toxicity.should_widen_spreads:
            logger.warning(
                "circuit_breaker.toxicity_warning",
                score=self._toxicity.score,
            )

    def reset_rapid_loss(self) -> None:
        self._rapid_loss.reset()
        logger.info("circuit_breaker.rapid_loss_reset")

    def reset_toxicity(self) -> None:
        self._toxicity.reset()
        logger.info("circuit_breaker.toxicity_reset")

    def reset_connection(self) -> None:
        self._connection_lost = False

    def reset_all(self) -> None:
        self.reset_rapid_loss()
        self.reset_toxicity()
        self.reset_connection()
        self._risk.resume()
        logger.info("circuit_breaker.all_reset")

    def get_status(self) -> list[BreakerStatus]:
        statuses = []

        # Rapid loss
        rl_state = CircuitBreakerState.OK
        rl_reason = ""
        if self._rapid_loss.is_tripped:
            rl_state = CircuitBreakerState.HALTED
            rl_reason = (
                f"{self._rapid_loss.loss_count} losses, "
                f"{self._rapid_loss.total_loss_cents}c total"
            )
        statuses.append(BreakerStatus("rapid_loss", rl_state, rl_reason))

        # Toxicity
        tx_state = CircuitBreakerState.OK
        tx_reason = ""
        if self._toxicity.should_pull_quotes:
            tx_state = CircuitBreakerState.HALTED
            tx_reason = f"Score {self._toxicity.score:.0f}"
        elif self._toxicity.should_widen_spreads:
            tx_state = CircuitBreakerState.WARNING
            tx_reason = f"Score {self._toxicity.score:.0f}"
        statuses.append(BreakerStatus("toxicity", tx_state, tx_reason))

        # Connection
        conn_state = (
            CircuitBreakerState.HALTED if self._connection_lost
            else CircuitBreakerState.OK
        )
        statuses.append(BreakerStatus("connection", conn_state))

        # Daily loss (from risk engine)
        daily_state = CircuitBreakerState.OK
        if self._risk.is_halted and "daily" in self._risk.halt_reason.lower():
            daily_state = CircuitBreakerState.HALTED
        statuses.append(BreakerStatus(
            "daily_loss", daily_state, self._risk.halt_reason
        ))

        return statuses

    @property
    def spread_multiplier(self) -> float:
        """Returns spread multiplier based on toxicity. 1.0 = normal."""
        if self._toxicity.should_pull_quotes:
            return 0.0  # Signal to pull quotes entirely
        if self._toxicity.should_widen_spreads:
            return 2.0
        return 1.0
