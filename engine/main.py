"""
Kalshi Market Making Engine — main entry point.

Phase 2: Minimal orchestrator that connects to Kalshi WebSocket,
scans for markets, runs the simple quoter, and logs to database.
"""

from __future__ import annotations

import asyncio
import signal
import sys

import structlog

from engine.core.config import load_config, validate_config
from engine.core.event_bus import EventBus
from engine.core.types import (
    ConnectionLost,
    ConnectionRestored,
    MarketPaused,
    MarketResolved,
    MarketResumed,
    Mode,
)
from engine.execution.paper_executor import PaperExecutor
from engine.market_data.orderbook import OrderbookManager
from engine.market_data.ws_client import KalshiWebSocketClient
from engine.market_data.market_scanner import MarketScanner
from engine.api.kalshi_rest import KalshiRestClient
from engine.risk.risk_engine import RiskEngine
from engine.strategy.simple_quoter import SimpleQuoter
from engine.storage.db_writer import DbWriter

logger = structlog.get_logger(__name__)


class Engine:
    def __init__(self) -> None:
        self._config = load_config()
        self._bus = EventBus()
        self._shutting_down = False

        # Core components
        self._orderbook_mgr = OrderbookManager()
        self._rest_client = KalshiRestClient(
            base_url=self._config.kalshi_base_url,
            api_key_id=self._config.kalshi_api_key_id,
            private_key_path=self._config.kalshi_private_key_path,
        )
        self._ws_client = KalshiWebSocketClient(
            config=self._config,
            bus=self._bus,
            orderbook_manager=self._orderbook_mgr,
        )
        self._scanner = MarketScanner(
            config=self._config,
            rest_client=self._rest_client,
        )
        self._db_writer = DbWriter(self._config.database_url) if self._config.database_url else None
        self._risk = RiskEngine(self._config)

        # Execution adapter (paper for now; live in Phase 5)
        if self._config.mode == Mode.PAPER:
            self._executor = PaperExecutor(
                bus=self._bus,
                starting_balance_cents=self._config.paper_starting_capital_cents,
            )
        else:
            # Live executor will be added in Phase 5
            self._executor = PaperExecutor(
                bus=self._bus,
                starting_balance_cents=self._config.paper_starting_capital_cents,
            )

        self._quoter = SimpleQuoter(
            config=self._config,
            bus=self._bus,
            executor=self._executor,
            risk_engine=self._risk,
        )

        # Wire up event handlers
        self._bus.subscribe(ConnectionLost, self._on_connection_lost)
        self._bus.subscribe(ConnectionRestored, self._on_connection_restored)
        self._bus.subscribe(MarketResolved, self._on_market_resolved)
        self._bus.subscribe(MarketPaused, self._on_market_paused)
        self._bus.subscribe(MarketResumed, self._on_market_resumed)

    async def run(self) -> None:
        """Start the engine and run until shutdown."""
        errors = validate_config(self._config)
        if errors:
            for e in errors:
                logger.error("config.validation_error", error=e)
            sys.exit(1)

        logger.info(
            "engine.starting",
            mode=self._config.mode.value,
            env=self._config.kalshi_env,
        )

        # Initialize clients
        await self._rest_client.start()
        if self._db_writer:
            await self._db_writer.start()

        # Initial market scan
        balance = await self._executor.get_balance_cents()
        markets = await self._scanner.scan(balance)
        tickers = [m.ticker for m in markets]

        if not tickers:
            logger.warning("engine.no_markets", msg="No markets passed filters")

        logger.info("engine.markets_selected", count=len(tickers), tickers=tickers[:5])

        # Build tasks
        tasks = [
            asyncio.create_task(self._ws_client.run(), name="ws_client"),
        ]

        if self._db_writer:
            tasks.append(asyncio.create_task(self._db_writer.flush_loop(), name="db_flush"))

        # Wait briefly for WS to connect, then subscribe
        await asyncio.sleep(2)
        if tickers:
            await self._ws_client.subscribe_markets(tickers)

        # Update engine status
        if self._db_writer:
            self._db_writer.update_engine_status(
                mode=self._config.mode,
                is_running=True,
                is_paused=False,
                connected=self._ws_client.is_connected,
                active_markets=tickers,
            )

        logger.info("engine.running", mode=self._config.mode.value)

        # Run until shutdown
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass
        finally:
            await self._shutdown()

    async def _shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True

        logger.info("engine.shutting_down")

        # Cancel all resting orders
        cancelled = await self._quoter.cancel_all_quotes()
        cancelled += await self._executor.cancel_all()
        logger.info("engine.orders_cancelled", count=cancelled)

        # Update status
        if self._db_writer:
            self._db_writer.update_engine_status(
                mode=self._config.mode,
                is_running=False,
                is_paused=False,
                connected=False,
                active_markets=[],
            )
            await self._db_writer.flush()
            await self._db_writer.close()

        await self._ws_client.stop()
        await self._rest_client.close()
        logger.info("engine.stopped")

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    async def _on_connection_lost(self, event: ConnectionLost) -> None:
        logger.warning("engine.connection_lost", reason=event.reason)
        await self._quoter.cancel_all_quotes()
        await self._executor.cancel_all()

    async def _on_connection_restored(self, event: ConnectionRestored) -> None:
        logger.info("engine.connection_restored")

    async def _on_market_resolved(self, event: MarketResolved) -> None:
        logger.info("engine.market_resolved", ticker=event.ticker, result=event.result)
        self._quoter.pause_market(event.ticker)
        self._orderbook_mgr.remove(event.ticker)

    async def _on_market_paused(self, event: MarketPaused) -> None:
        logger.info("engine.market_paused", ticker=event.ticker)
        self._quoter.pause_market(event.ticker)
        # Cancel resting orders on paused market
        resting = self._quoter._resting.get(event.ticker, (None, None))
        for oid in resting:
            if oid:
                await self._executor.cancel_order(oid)

    async def _on_market_resumed(self, event: MarketResumed) -> None:
        logger.info("engine.market_resumed", ticker=event.ticker)
        self._quoter.resume_market(event.ticker)


def _setup_signal_handlers(engine: Engine, loop: asyncio.AbstractEventLoop) -> None:
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(engine._shutdown()))


async def main() -> None:
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(0),
    )

    engine = Engine()

    loop = asyncio.get_running_loop()
    try:
        _setup_signal_handlers(engine, loop)
    except NotImplementedError:
        pass  # Windows doesn't support add_signal_handler

    await engine.run()


if __name__ == "__main__":
    asyncio.run(main())
