"""
Core types for the Kalshi market making engine.

All prices are in CENTS (1-99 for Kalshi binary markets).
All balances and P&L values are in CENTS.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Literal
from uuid import uuid4


class Mode(str, Enum):
    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"


class Side(str, Enum):
    YES = "yes"
    NO = "no"


class Action(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, Enum):
    PENDING = "pending"
    RESTING = "resting"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class CircuitBreakerState(str, Enum):
    OK = "ok"
    WARNING = "warning"
    HALTED = "halted"


# ---------------------------------------------------------------------------
# Market data types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OrderbookLevel:
    price_cents: int
    quantity: int


@dataclass
class Orderbook:
    ticker: str
    yes_bids: list[OrderbookLevel] = field(default_factory=list)
    yes_asks: list[OrderbookLevel] = field(default_factory=list)
    last_updated: datetime = field(default_factory=lambda: datetime.now(UTC))

    def mid_price_cents(self) -> float:
        if not self.yes_bids or not self.yes_asks:
            return 50.0
        best_bid = self.yes_bids[0].price_cents
        best_ask = self.yes_asks[0].price_cents
        return (best_bid + best_ask) / 2.0

    def spread_cents(self) -> int:
        if not self.yes_bids or not self.yes_asks:
            return 99
        return self.yes_asks[0].price_cents - self.yes_bids[0].price_cents

    def best_bid(self) -> int | None:
        return self.yes_bids[0].price_cents if self.yes_bids else None

    def best_ask(self) -> int | None:
        return self.yes_asks[0].price_cents if self.yes_asks else None


@dataclass
class MarketInfo:
    ticker: str
    event_ticker: str
    title: str
    status: str
    yes_bid_cents: int | None = None
    yes_ask_cents: int | None = None
    volume_24h: int = 0
    open_interest: int = 0
    close_time: datetime | None = None
    result: str | None = None


# ---------------------------------------------------------------------------
# Trading types
# ---------------------------------------------------------------------------

@dataclass
class InventoryState:
    ticker: str
    net_position: int = 0
    cost_basis_cents: int = 0
    unrealized_pnl_cents: int = 0
    realized_pnl_cents: int = 0

    @property
    def is_long(self) -> bool:
        return self.net_position > 0

    @property
    def is_short(self) -> bool:
        return self.net_position < 0

    @property
    def is_flat(self) -> bool:
        return self.net_position == 0


@dataclass(frozen=True)
class Quote:
    ticker: str
    bid_price_cents: int
    bid_size: int
    ask_price_cents: int
    ask_size: int
    fair_value_cents: float
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class OrderRequest:
    ticker: str
    side: Side
    action: Action
    count: int
    price_cents: int
    client_order_id: str = field(default_factory=lambda: str(uuid4()))
    post_only: bool = True
    time_in_force: str = "good_till_canceled"

    @property
    def notional_cents(self) -> int:
        return self.count * self.price_cents


@dataclass
class OrderAck:
    order_id: str
    client_order_id: str
    status: str
    ticker: str
    side: Side
    action: Action
    price_cents: int
    count: int
    remaining_count: int = 0
    error: str | None = None

    @property
    def is_success(self) -> bool:
        return self.error is None


@dataclass
class Fill:
    fill_id: str
    order_id: str
    ticker: str
    side: Side
    action: Action
    count: int
    price_cents: int
    fee_cents: int
    is_maker: bool
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    pnl_cents: int = 0


@dataclass
class RiskViolation:
    rule: str
    severity: Literal["warn", "block", "halt"]
    detail: str


# ---------------------------------------------------------------------------
# Event types (for the event bus)
# ---------------------------------------------------------------------------

@dataclass
class OrderbookUpdate:
    ticker: str
    orderbook: Orderbook


@dataclass
class FillEvent:
    fill: Fill


@dataclass
class OrderAckEvent:
    ack: OrderAck


@dataclass
class RiskViolationEvent:
    violation: RiskViolation


@dataclass
class ConfigChanged:
    changed_keys: list[str]


@dataclass
class ConnectionLost:
    reason: str


@dataclass
class ConnectionRestored:
    pass


@dataclass
class MarketResolved:
    ticker: str
    result: str


@dataclass
class MarketPaused:
    ticker: str


@dataclass
class MarketResumed:
    ticker: str


@dataclass
class QuoteGenerated:
    quote: Quote


# ---------------------------------------------------------------------------
# Fee calculation
# ---------------------------------------------------------------------------

def taker_fee_cents(count: int, price_cents: int) -> int:
    """Calculate taker fee in cents. Formula: ceil(0.07 * C * P * (1 - P))"""
    p = price_cents / 100.0
    return math.ceil(0.07 * count * p * (1.0 - p))


def maker_fee_cents(count: int, price_cents: int) -> int:
    """Calculate maker fee in cents. Formula: ceil(0.0175 * C * P * (1 - P))"""
    p = price_cents / 100.0
    return math.ceil(0.0175 * count * p * (1.0 - p))


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class EngineConfig:
    mode: Mode = Mode.PAPER
    kalshi_api_key_id: str = ""
    kalshi_private_key_path: str = ""
    kalshi_env: str = "demo"
    database_url: str = ""
    telegram_token: str = ""
    telegram_chat_id: str = ""
    paper_starting_capital_cents: int = 10000
    log_level: str = "INFO"

    # Risk parameters (hot-reloadable from DB)
    max_position_per_market: int = 10
    global_exposure_limit_cents: int = 10000
    daily_loss_limit_cents: int = 1000
    drawdown_limit: float = 0.10

    # Strategy parameters (hot-reloadable from DB)
    base_gamma: float = 0.3
    sigma: float = 0.15
    min_spread_cents: int = 3
    order_size: int = 5
    signal_weight: float = 0.0

    # Market selection (hot-reloadable from DB)
    min_volume: int = 100
    max_market_spread_cents: int = 10
    min_time_to_expiry_seconds: int = 3600

    # Paper trading milestone (advisory)
    paper_milestone_days: int = 30

    # Polling
    settings_poll_interval_seconds: int = 5
    reconciliation_interval_seconds: int = 30
    snapshot_interval_seconds: int = 300

    @property
    def kalshi_base_url(self) -> str:
        if self.kalshi_env == "demo":
            return "https://demo-api.kalshi.co/trade-api/v2"
        return "https://api.elections.kalshi.com/trade-api/v2"

    @property
    def kalshi_ws_url(self) -> str:
        if self.kalshi_env == "demo":
            return "wss://demo-api.kalshi.co/trade-api/ws/v2"
        return "wss://api.elections.kalshi.com/trade-api/ws/v2"
