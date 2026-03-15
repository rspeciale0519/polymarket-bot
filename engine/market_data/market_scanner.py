"""
Automated market selection.

Evaluates all open Kalshi markets against configurable criteria and
selects which ones the engine should quote. Runs on startup and daily.
Capital-aware: limits active market count based on available balance.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from engine.api.kalshi_rest import KalshiRestClient
from engine.core.types import EngineConfig, MarketInfo

logger = structlog.get_logger(__name__)

# Capital-to-market-count mapping (balance_cents → max markets)
CAPITAL_MARKET_LIMITS = [
    (25000, 15),   # $250+ → up to 15 markets
    (10000, 8),    # $100-250 → up to 8
    (5000, 5),     # $50-100 → up to 5
    (2500, 3),     # $25-50 → up to 3
    (0, 2),        # <$25 → 2 markets
]


class MarketScanner:
    def __init__(
        self,
        config: EngineConfig,
        rest_client: KalshiRestClient,
    ) -> None:
        self._config = config
        self._rest = rest_client
        self._markets: list[MarketInfo] = []

    async def scan(self, balance_cents: int = 0) -> list[MarketInfo]:
        """Scan all open markets and filter by criteria."""
        logger.info("market_scanner.scanning")

        all_markets = await self._fetch_all_open_markets()
        filtered = self._apply_filters(all_markets)
        max_markets = _max_markets_for_balance(balance_cents)
        selected = filtered[:max_markets]

        self._markets = selected
        logger.info(
            "market_scanner.complete",
            total_open=len(all_markets),
            after_filter=len(filtered),
            selected=len(selected),
            max_allowed=max_markets,
        )
        return selected

    async def run_daily(self, balance_cents_fn: Any = None) -> None:
        """Run the scanner once daily as a background task."""
        while True:
            try:
                balance = 0
                if balance_cents_fn:
                    balance = await balance_cents_fn()
                await self.scan(balance)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("market_scanner.daily_error")

            await asyncio.sleep(86400)  # 24 hours

    @property
    def selected_markets(self) -> list[MarketInfo]:
        return list(self._markets)

    @property
    def selected_tickers(self) -> list[str]:
        return [m.ticker for m in self._markets]

    async def _fetch_all_open_markets(self) -> list[MarketInfo]:
        """Fetch all open markets from Kalshi API with pagination."""
        markets: list[MarketInfo] = []
        cursor: str | None = None

        while True:
            data = await self._rest.get_markets(
                status="open", limit=200, cursor=cursor
            )
            raw_markets = data.get("markets", [])
            if not raw_markets:
                break

            for m in raw_markets:
                info = _parse_market(m)
                if info:
                    markets.append(info)

            cursor = data.get("cursor")
            if not cursor:
                break

        return markets

    def _apply_filters(self, markets: list[MarketInfo]) -> list[MarketInfo]:
        """Filter markets by configured criteria."""
        now = datetime.now(UTC)
        results = []

        for m in markets:
            if m.status != "active":
                continue

            if m.volume_24h < self._config.min_volume:
                continue

            if m.close_time:
                remaining = (m.close_time - now).total_seconds()
                if remaining < self._config.min_time_to_expiry_seconds:
                    continue

            # Spread filter: only if we have bid/ask data
            if m.yes_bid_cents and m.yes_ask_cents:
                spread = m.yes_ask_cents - m.yes_bid_cents
                if spread > self._config.max_market_spread_cents:
                    continue

            results.append(m)

        # Sort by volume descending (most liquid first)
        results.sort(key=lambda m: m.volume_24h, reverse=True)
        return results


def _parse_market(raw: dict[str, Any]) -> MarketInfo | None:
    """Parse a raw market dict from the Kalshi API into MarketInfo."""
    ticker = raw.get("ticker")
    if not ticker:
        return None

    close_time = None
    close_str = raw.get("close_time")
    if close_str:
        try:
            close_time = datetime.fromisoformat(close_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass

    yes_bid = _dollars_to_cents(raw.get("yes_bid_dollars"))
    yes_ask = _dollars_to_cents(raw.get("yes_ask_dollars"))
    volume = int(float(raw.get("volume_24h_fp", raw.get("volume_24h", 0)) or 0))
    oi = int(float(raw.get("open_interest_fp", raw.get("open_interest", 0)) or 0))

    return MarketInfo(
        ticker=ticker,
        event_ticker=raw.get("event_ticker", ""),
        title=raw.get("title", raw.get("subtitle", ticker)),
        status=raw.get("status", "unknown"),
        yes_bid_cents=yes_bid,
        yes_ask_cents=yes_ask,
        volume_24h=volume,
        open_interest=oi,
        close_time=close_time,
        result=raw.get("result"),
    )


def _dollars_to_cents(val: Any) -> int | None:
    if val is None:
        return None
    try:
        return int(float(val) * 100)
    except (ValueError, TypeError):
        return None


def _max_markets_for_balance(balance_cents: int) -> int:
    for threshold, max_markets in CAPITAL_MARKET_LIMITS:
        if balance_cents >= threshold:
            return max_markets
    return 2
