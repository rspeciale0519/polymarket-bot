"""
Historical data loader for backtesting.

Downloads historical trades and candlesticks from the Kalshi API.
Caches data to local JSON files to avoid re-downloading.
Returns structured tick data for the backtest runner.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

import structlog

from engine.api.kalshi_rest import KalshiRestClient
from engine.core.types import Orderbook, OrderbookLevel

logger = structlog.get_logger(__name__)

DEFAULT_CACHE_DIR = ".backtest_cache"


@dataclass
class HistoricalTick:
    """A single point-in-time snapshot for backtesting."""
    timestamp: datetime
    ticker: str
    yes_bid_cents: int
    yes_ask_cents: int
    volume: int = 0
    open_interest: int = 0

    def to_orderbook(self) -> Orderbook:
        """Convert to a simple Orderbook with single-level depth."""
        return Orderbook(
            ticker=self.ticker,
            yes_bids=[OrderbookLevel(self.yes_bid_cents, 100)],
            yes_asks=[OrderbookLevel(self.yes_ask_cents, 100)],
            last_updated=self.timestamp,
        )


@dataclass
class HistoricalDataset:
    """A complete dataset for backtesting a single market."""
    ticker: str
    series_ticker: str
    ticks: list[HistoricalTick] = field(default_factory=list)
    start_time: datetime | None = None
    end_time: datetime | None = None

    @property
    def duration_hours(self) -> float:
        if not self.start_time or not self.end_time:
            return 0.0
        return (self.end_time - self.start_time).total_seconds() / 3600


class DataLoader:
    """Loads historical market data for backtesting."""

    def __init__(
        self,
        rest_client: KalshiRestClient,
        cache_dir: str = DEFAULT_CACHE_DIR,
    ) -> None:
        self._rest = rest_client
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    async def load_candlesticks(
        self,
        series_ticker: str,
        ticker: str,
        start_ts: int,
        end_ts: int,
        period_minutes: int = 1,
    ) -> HistoricalDataset:
        """
        Load candlestick data for a market.

        Args:
            series_ticker: Event series (e.g. "KXBTCD")
            ticker: Market ticker (e.g. "KXBTCD-25DEC31-T50000")
            start_ts: Start timestamp (unix seconds)
            end_ts: End timestamp (unix seconds)
            period_minutes: Candle period (1, 60, or 1440)

        Returns:
            HistoricalDataset with ticks derived from candlesticks.
        """
        cache_key = f"{ticker}_{start_ts}_{end_ts}_{period_minutes}"
        cached = self._load_cache(cache_key)
        if cached:
            logger.info("data_loader.cache_hit", ticker=ticker, ticks=len(cached.ticks))
            return cached

        logger.info("data_loader.fetching", ticker=ticker, start=start_ts, end=end_ts)

        try:
            data = await self._rest._request(
                "GET",
                f"/series/{series_ticker}/markets/{ticker}/candlesticks",
                params={
                    "start_ts": start_ts,
                    "end_ts": end_ts,
                    "period_interval": period_minutes,
                },
            )
        except Exception:
            logger.exception("data_loader.fetch_error", ticker=ticker)
            return HistoricalDataset(ticker=ticker, series_ticker=series_ticker)

        candles = data.get("candlesticks", [])
        ticks = []

        for candle in candles:
            tick = _parse_candlestick(ticker, candle)
            if tick:
                ticks.append(tick)

        ticks.sort(key=lambda t: t.timestamp)

        dataset = HistoricalDataset(
            ticker=ticker,
            series_ticker=series_ticker,
            ticks=ticks,
            start_time=ticks[0].timestamp if ticks else None,
            end_time=ticks[-1].timestamp if ticks else None,
        )

        self._save_cache(cache_key, dataset)
        logger.info("data_loader.loaded", ticker=ticker, ticks=len(ticks))
        return dataset

    async def load_trades(
        self,
        ticker: str,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Load recent trade history for a market."""
        cache_key = f"trades_{ticker}_{limit}"
        cached_raw = self._load_raw_cache(cache_key)
        if cached_raw:
            return cached_raw

        all_trades: list[dict] = []
        cursor: str | None = None

        while len(all_trades) < limit:
            batch_limit = min(limit - len(all_trades), 100)
            data = await self._rest.get_trades(
                ticker=ticker, limit=batch_limit, cursor=cursor
            )
            trades = data.get("trades", [])
            if not trades:
                break
            all_trades.extend(trades)
            cursor = data.get("cursor")
            if not cursor:
                break

        self._save_raw_cache(cache_key, all_trades)
        return all_trades

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _cache_path(self, key: str) -> Path:
        safe_key = key.replace("/", "_").replace(":", "_")
        return self._cache_dir / f"{safe_key}.json"

    def _load_cache(self, key: str) -> HistoricalDataset | None:
        path = self._cache_path(key)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text())
            ticks = [
                HistoricalTick(
                    timestamp=datetime.fromisoformat(t["timestamp"]),
                    ticker=t["ticker"],
                    yes_bid_cents=t["yes_bid_cents"],
                    yes_ask_cents=t["yes_ask_cents"],
                    volume=t.get("volume", 0),
                    open_interest=t.get("open_interest", 0),
                )
                for t in raw.get("ticks", [])
            ]
            return HistoricalDataset(
                ticker=raw["ticker"],
                series_ticker=raw.get("series_ticker", ""),
                ticks=ticks,
                start_time=ticks[0].timestamp if ticks else None,
                end_time=ticks[-1].timestamp if ticks else None,
            )
        except Exception:
            logger.warning("data_loader.cache_corrupt", key=key)
            return None

    def _save_cache(self, key: str, dataset: HistoricalDataset) -> None:
        path = self._cache_path(key)
        raw = {
            "ticker": dataset.ticker,
            "series_ticker": dataset.series_ticker,
            "ticks": [
                {
                    "timestamp": t.timestamp.isoformat(),
                    "ticker": t.ticker,
                    "yes_bid_cents": t.yes_bid_cents,
                    "yes_ask_cents": t.yes_ask_cents,
                    "volume": t.volume,
                    "open_interest": t.open_interest,
                }
                for t in dataset.ticks
            ],
        }
        path.write_text(json.dumps(raw))

    def _load_raw_cache(self, key: str) -> list | None:
        path = self._cache_path(key)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except Exception:
            return None

    def _save_raw_cache(self, key: str, data: list) -> None:
        path = self._cache_path(key)
        path.write_text(json.dumps(data))


def _parse_candlestick(ticker: str, candle: dict) -> HistoricalTick | None:
    """Parse a single candlestick into a HistoricalTick."""
    try:
        ts = candle.get("end_period_ts", 0)
        if not ts:
            return None

        timestamp = datetime.fromtimestamp(ts, tz=UTC)

        price_data = candle.get("price", {})
        yes_bid_data = candle.get("yes_bid", {})
        yes_ask_data = candle.get("yes_ask", {})

        bid_close = yes_bid_data.get("close", price_data.get("close", "0.50"))
        ask_close = yes_ask_data.get("close", price_data.get("close", "0.50"))

        bid_cents = int(float(bid_close) * 100)
        ask_cents = int(float(ask_close) * 100)

        if bid_cents >= ask_cents:
            ask_cents = bid_cents + 1

        volume = int(float(candle.get("volume_fp", "0")))
        oi = int(float(candle.get("open_interest_fp", "0")))

        return HistoricalTick(
            timestamp=timestamp,
            ticker=ticker,
            yes_bid_cents=max(1, min(98, bid_cents)),
            yes_ask_cents=max(2, min(99, ask_cents)),
            volume=volume,
            open_interest=oi,
        )
    except Exception:
        return None
