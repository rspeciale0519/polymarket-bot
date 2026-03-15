"""
Directional signal aggregation.

Maintains per-market signal in [-1.0, 1.0] (bearish to bullish).
Combines internal signals (volume imbalance, trade momentum) into
a directional skew that shifts the AS reservation price.

Default signal_weight = 0.0 means pure market making with no directional
bias. Can be increased to blend in directional conviction.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime

import structlog

from engine.core.event_bus import EventBus
from engine.core.types import EngineConfig, OrderbookUpdate

logger = structlog.get_logger(__name__)


@dataclass
class MarketSignal:
    """Aggregated signal state for a single market."""
    volume_imbalance: float = 0.0   # [-1, 1]: -1 = all sells, +1 = all buys
    trade_momentum: float = 0.0     # [-1, 1]: direction of recent price moves
    combined: float = 0.0           # weighted average of all signals


class SignalIntegrator:
    """Aggregates directional signals per market."""

    def __init__(self, config: EngineConfig, bus: EventBus) -> None:
        self._config = config
        self._bus = bus
        self._signals: dict[str, MarketSignal] = {}
        self._price_history: dict[str, deque[float]] = {}
        self._trade_sides: dict[str, deque[int]] = {}  # +1 buy, -1 sell

        self._bus.subscribe(OrderbookUpdate, self._on_orderbook_update)

    def get_signal(self, ticker: str) -> MarketSignal:
        if ticker not in self._signals:
            self._signals[ticker] = MarketSignal()
        return self._signals[ticker]

    def get_directional_skew_cents(self, ticker: str) -> float:
        """
        Returns the directional skew to apply to the reservation price,
        in cents. Positive = bullish (shift quotes up).

        Scaled by config.signal_weight. At weight=0, returns 0 always.
        """
        if self._config.signal_weight <= 0:
            return 0.0

        signal = self.get_signal(ticker)
        # Max skew: +/- 5 cents at full signal and full weight
        max_skew_cents = 5.0
        return signal.combined * self._config.signal_weight * max_skew_cents

    def record_trade(self, ticker: str, is_buy: bool, price_cents: float) -> None:
        """Record a public trade for signal calculation."""
        # Track trade direction
        if ticker not in self._trade_sides:
            self._trade_sides[ticker] = deque(maxlen=50)
        self._trade_sides[ticker].append(1 if is_buy else -1)

        # Track price history for momentum
        if ticker not in self._price_history:
            self._price_history[ticker] = deque(maxlen=50)
        self._price_history[ticker].append(price_cents)

        self._recompute(ticker)

    async def _on_orderbook_update(self, event: OrderbookUpdate) -> None:
        """Update signals based on orderbook imbalance."""
        book = event.orderbook
        ticker = event.ticker

        if not book.yes_bids or not book.yes_asks:
            return

        # Volume imbalance from orderbook depth
        total_bid_qty = sum(l.quantity for l in book.yes_bids[:5])
        total_ask_qty = sum(l.quantity for l in book.yes_asks[:5])
        total = total_bid_qty + total_ask_qty

        signal = self.get_signal(ticker)
        if total > 0:
            signal.volume_imbalance = (total_bid_qty - total_ask_qty) / total
        else:
            signal.volume_imbalance = 0.0

        self._recompute(ticker)

    def _recompute(self, ticker: str) -> None:
        """Recompute combined signal from all sources."""
        signal = self.get_signal(ticker)

        # Trade momentum: average direction of last N trades
        trades = self._trade_sides.get(ticker)
        if trades and len(trades) >= 5:
            signal.trade_momentum = sum(trades) / len(trades)
        else:
            signal.trade_momentum = 0.0

        # Weighted combination
        # Volume imbalance is more reliable than trade momentum
        signal.combined = (
            0.6 * signal.volume_imbalance +
            0.4 * signal.trade_momentum
        )

        # Clamp to [-1, 1]
        signal.combined = max(-1.0, min(1.0, signal.combined))

    def reset(self, ticker: str) -> None:
        """Reset all signals for a market."""
        self._signals.pop(ticker, None)
        self._price_history.pop(ticker, None)
        self._trade_sides.pop(ticker, None)
