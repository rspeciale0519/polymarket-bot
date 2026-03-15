"""
Kalshi WebSocket client with automatic reconnection.

Maintains a persistent connection to Kalshi's WS API, subscribes to
orderbook, trade, fill, and market lifecycle channels. On disconnect,
publishes ConnectionLost and triggers emergency cancel-all.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from typing import Any

import structlog
import websockets
from websockets.exceptions import ConnectionClosed

from engine.api.auth import build_auth_headers, load_private_key
from engine.core.event_bus import EventBus
from engine.core.types import (
    ConnectionLost,
    ConnectionRestored,
    EngineConfig,
    FillEvent,
    MarketPaused,
    MarketResolved,
    MarketResumed,
    OrderAckEvent,
    OrderbookUpdate,
)
from engine.market_data.orderbook import OrderbookManager

logger = structlog.get_logger(__name__)

BACKOFF_BASE = 1.0
BACKOFF_MAX = 30.0
BACKOFF_JITTER = 0.25


class KalshiWebSocketClient:
    def __init__(
        self,
        config: EngineConfig,
        bus: EventBus,
        orderbook_manager: OrderbookManager,
    ) -> None:
        self._config = config
        self._bus = bus
        self._orderbook_mgr = orderbook_manager
        self._private_key = None
        self._ws: Any = None
        self._subscribed_tickers: set[str] = set()
        self._next_id = 1
        self._connected = False
        self._shutdown = False

    async def run(self) -> None:
        """Main connection loop with exponential backoff reconnection."""
        if self._config.kalshi_private_key_path:
            self._private_key = load_private_key(self._config.kalshi_private_key_path)

        attempt = 0
        while not self._shutdown:
            try:
                await self._connect_and_listen()
                attempt = 0
            except (ConnectionClosed, ConnectionError, OSError) as e:
                if self._shutdown:
                    break
                self._connected = False
                await self._bus.publish(ConnectionLost(reason=str(e)))
                delay = _backoff_delay(attempt)
                logger.warning("ws.disconnected", error=str(e), reconnect_in=delay)
                await asyncio.sleep(delay)
                attempt += 1
            except asyncio.CancelledError:
                break
            except Exception as e:
                if self._shutdown:
                    break
                self._connected = False
                await self._bus.publish(ConnectionLost(reason=str(e)))
                delay = _backoff_delay(attempt)
                logger.exception("ws.unexpected_error", reconnect_in=delay)
                await asyncio.sleep(delay)
                attempt += 1

    async def stop(self) -> None:
        self._shutdown = True
        if self._ws:
            await self._ws.close()

    async def subscribe_markets(self, tickers: list[str]) -> None:
        """Subscribe to orderbook + trade channels for given tickers."""
        new_tickers = [t for t in tickers if t not in self._subscribed_tickers]
        if not new_tickers or not self._ws:
            return

        msg = {
            "id": self._next_msg_id(),
            "cmd": "subscribe",
            "params": {
                "channels": ["orderbook_delta", "trade"],
                "market_tickers": new_tickers,
                "send_initial_snapshot": True,
            },
        }
        await self._ws.send(json.dumps(msg))
        self._subscribed_tickers.update(new_tickers)
        logger.info("ws.subscribed_markets", tickers=new_tickers)

    async def unsubscribe_market(self, ticker: str) -> None:
        """Remove a market from subscriptions."""
        self._subscribed_tickers.discard(ticker)
        # Kalshi doesn't have per-market unsubscribe — we track locally
        # and ignore messages for unsubscribed tickers

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _connect_and_listen(self) -> None:
        url = self._config.kalshi_ws_url
        headers = self._ws_auth_headers()

        async with websockets.connect(url, additional_headers=headers) as ws:
            self._ws = ws
            self._connected = True
            logger.info("ws.connected", url=url)
            await self._bus.publish(ConnectionRestored())

            # Subscribe to user-level channels
            await self._subscribe_user_channels()

            # Resubscribe to previously tracked markets
            if self._subscribed_tickers:
                tickers = list(self._subscribed_tickers)
                self._subscribed_tickers.clear()
                await self.subscribe_markets(tickers)

            async for raw_msg in ws:
                await self._handle_message(raw_msg)

    async def _subscribe_user_channels(self) -> None:
        """Subscribe to fill, user_orders, and market_lifecycle channels."""
        if not self._ws:
            return
        msg = {
            "id": self._next_msg_id(),
            "cmd": "subscribe",
            "params": {
                "channels": ["fill", "user_orders", "market_lifecycle_v2"],
            },
        }
        await self._ws.send(json.dumps(msg))

    async def _handle_message(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("ws.invalid_json", raw=raw[:100])
            return

        msg_type = data.get("type", "")

        if msg_type in ("orderbook_snapshot", "orderbook_delta"):
            await self._handle_orderbook(msg_type, data)
        elif msg_type == "trade":
            pass  # Trade events used later for signal integrator
        elif msg_type == "fill":
            await self._handle_fill(data)
        elif msg_type == "user_order":
            await self._handle_user_order(data)
        elif msg_type in ("market_determined", "market_closed", "market_finalized"):
            await self._handle_market_resolved(data)
        elif msg_type == "market_paused":
            await self._handle_market_paused(data)
        elif msg_type == "market_active":
            await self._handle_market_resumed(data)
        elif msg_type == "subscribed":
            logger.debug("ws.subscribed", sid=data.get("sid"))
        elif msg_type == "error":
            logger.error("ws.error", data=data)

    async def _handle_orderbook(self, msg_type: str, data: dict) -> None:
        msg = data.get("msg", data)
        ticker = msg.get("market_ticker", "")

        if ticker not in self._subscribed_tickers:
            return

        if msg_type == "orderbook_snapshot":
            orderbook = self._orderbook_mgr.apply_snapshot(ticker, msg)
        else:
            orderbook = self._orderbook_mgr.apply_delta(ticker, msg)

        if orderbook:
            await self._bus.publish(OrderbookUpdate(ticker=ticker, orderbook=orderbook))

    async def _handle_fill(self, data: dict) -> None:
        from engine.core.types import Action, Fill, Side

        msg = data.get("msg", data)
        fill = Fill(
            fill_id=msg.get("trade_id", msg.get("fill_id", "")),
            order_id=msg.get("order_id", ""),
            ticker=msg.get("ticker", msg.get("market_ticker", "")),
            side=Side(msg.get("side", "yes")),
            action=Action(msg.get("action", "buy")),
            count=int(float(msg.get("count_fp", msg.get("count", 0)))),
            price_cents=_parse_price(msg),
            fee_cents=int(msg.get("fee_cost", 0)),
            is_maker=not msg.get("is_taker", False),
        )
        await self._bus.publish(FillEvent(fill=fill))

    async def _handle_user_order(self, data: dict) -> None:
        from engine.core.types import Action, OrderAck, Side

        msg = data.get("msg", data)
        ack = OrderAck(
            order_id=msg.get("order_id", ""),
            client_order_id=msg.get("client_order_id", ""),
            status=msg.get("status", "unknown"),
            ticker=msg.get("ticker", ""),
            side=Side(msg.get("side", "yes")),
            action=Action(msg.get("action", "buy")),
            price_cents=_parse_price(msg),
            count=int(float(msg.get("initial_count_fp", "0"))),
            remaining_count=int(float(msg.get("remaining_count_fp", "0"))),
        )
        await self._bus.publish(OrderAckEvent(ack=ack))

    async def _handle_market_resolved(self, data: dict) -> None:
        msg = data.get("msg", data)
        ticker = msg.get("market_ticker", msg.get("ticker", ""))
        result = msg.get("result", msg.get("settlement_value", ""))
        if ticker:
            self._subscribed_tickers.discard(ticker)
            await self._bus.publish(MarketResolved(ticker=ticker, result=str(result)))

    async def _handle_market_paused(self, data: dict) -> None:
        msg = data.get("msg", data)
        ticker = msg.get("market_ticker", msg.get("ticker", ""))
        if ticker:
            await self._bus.publish(MarketPaused(ticker=ticker))

    async def _handle_market_resumed(self, data: dict) -> None:
        msg = data.get("msg", data)
        ticker = msg.get("market_ticker", msg.get("ticker", ""))
        if ticker:
            await self._bus.publish(MarketResumed(ticker=ticker))

    def _ws_auth_headers(self) -> dict[str, str]:
        if not self._private_key:
            return {}
        return build_auth_headers(
            self._config.kalshi_api_key_id,
            self._private_key,
            "GET",
            "/trade-api/ws/v2",
        )

    def _next_msg_id(self) -> int:
        mid = self._next_id
        self._next_id += 1
        return mid


def _backoff_delay(attempt: int) -> float:
    delay = min(BACKOFF_BASE * (2 ** attempt), BACKOFF_MAX)
    jitter = delay * BACKOFF_JITTER * random.random()
    return delay + jitter


def _parse_price(msg: dict) -> int:
    """Extract price in cents from various Kalshi message formats."""
    if "yes_price" in msg:
        return int(msg["yes_price"])
    if "yes_price_dollars" in msg:
        return int(float(msg["yes_price_dollars"]) * 100)
    if "no_price" in msg:
        return 100 - int(msg["no_price"])
    if "no_price_dollars" in msg:
        return 100 - int(float(msg["no_price_dollars"]) * 100)
    return 50
