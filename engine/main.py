"""
Kalshi Market Making Engine — main entry point.

Full orchestrator: WebSocket, market scanner, simple quoter, risk engine,
circuit breakers, position tracker, order reconciler, Telegram bot,
settings poller, portfolio snapshots. Graceful shutdown on SIGINT/SIGTERM.
"""

from __future__ import annotations

import asyncio
import signal
import sys

import structlog

from engine.api.kalshi_rest import KalshiRestClient
from engine.core.config import load_config, validate_config
from engine.core.event_bus import EventBus
from engine.core.types import (
    ConfigChanged,
    ConnectionLost,
    ConnectionRestored,
    FillEvent,
    MarketPaused,
    MarketResolved,
    MarketResumed,
    Mode,
)
from engine.dashboard_bridge.settings_poller import SettingsPoller
from engine.execution.order_reconciler import OrderReconciler
from engine.execution.paper_executor import PaperExecutor
from engine.market_data.market_scanner import MarketScanner
from engine.market_data.orderbook import OrderbookManager
from engine.market_data.ws_client import KalshiWebSocketClient
from engine.notifications.formatters import (
    format_breaker_status,
    format_daily_report,
    format_fill,
    format_positions,
    format_risk_summary,
)
from engine.notifications.telegram_bot import TelegramNotifier
from engine.risk.circuit_breakers import CircuitBreakerManager
from engine.risk.position_tracker import PositionTracker
from engine.risk.risk_engine import RiskEngine
from engine.storage.db_writer import DbWriter
from engine.strategy.simple_quoter import SimpleQuoter

logger = structlog.get_logger(__name__)


class Engine:
    def __init__(self) -> None:
        self._config = load_config()
        self._bus = EventBus()
        self._shutting_down = False
        self._paused = False

        # Core infrastructure
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
        self._db = (
            DbWriter(self._config.database_url)
            if self._config.database_url else None
        )

        # Risk
        self._risk = RiskEngine(self._config)
        self._circuit_breakers = CircuitBreakerManager(
            bus=self._bus,
            risk_engine=self._risk,
        )

        # Execution
        if self._config.mode == Mode.PAPER:
            self._executor = PaperExecutor(
                bus=self._bus,
                starting_balance_cents=self._config.paper_starting_capital_cents,
            )
        else:
            # Live executor added in Phase 5
            self._executor = PaperExecutor(
                bus=self._bus,
                starting_balance_cents=self._config.paper_starting_capital_cents,
            )

        # Position tracking
        self._position_tracker = PositionTracker(
            bus=self._bus,
            risk_engine=self._risk,
            db_writer=self._db,
            mode=self._config.mode,
        )

        # Strategy
        self._quoter = SimpleQuoter(
            config=self._config,
            bus=self._bus,
            executor=self._executor,
            risk_engine=self._risk,
        )

        # Order reconciliation
        self._reconciler = OrderReconciler(
            config=self._config,
            rest_client=self._rest_client,
            executor=self._executor,
        )

        # Telegram
        self._telegram = TelegramNotifier(
            token=self._config.telegram_token,
            chat_id=self._config.telegram_chat_id,
        )
        self._telegram.set_callbacks(
            on_pause=self._handle_pause,
            on_resume=self._handle_resume,
            get_status=self._handle_get_status,
            get_risk=self._handle_get_risk,
            get_positions=self._handle_get_positions,
        )

        # Settings poller
        self._settings_poller = (
            SettingsPoller(self._config, self._bus, self._db)
            if self._db else None
        )

        # Wire event handlers
        self._bus.subscribe(ConnectionLost, self._on_connection_lost)
        self._bus.subscribe(ConnectionRestored, self._on_connection_restored)
        self._bus.subscribe(MarketResolved, self._on_market_resolved)
        self._bus.subscribe(MarketPaused, self._on_market_paused)
        self._bus.subscribe(MarketResumed, self._on_market_resumed)
        self._bus.subscribe(FillEvent, self._on_fill)
        self._bus.subscribe(ConfigChanged, self._on_config_changed)

    async def run(self) -> None:
        errors = validate_config(self._config)
        if errors:
            for e in errors:
                logger.error("config.error", error=e)
            sys.exit(1)

        logger.info("engine.starting", mode=self._config.mode.value,
                     env=self._config.kalshi_env)

        await self._rest_client.start()
        if self._db:
            await self._db.start()

        # Initial market scan
        balance = await self._executor.get_balance_cents()
        markets = await self._scanner.scan(balance)
        tickers = [m.ticker for m in markets]
        logger.info("engine.markets", count=len(tickers), tickers=tickers[:5])

        # Build async tasks
        tasks = [
            asyncio.create_task(self._ws_client.run(), name="ws"),
            asyncio.create_task(self._telegram.run(), name="telegram"),
            asyncio.create_task(self._reconciler.run(), name="reconciler"),
            asyncio.create_task(self._snapshot_loop(), name="snapshots"),
        ]
        if self._db:
            tasks.append(asyncio.create_task(self._db.flush_loop(), name="db_flush"))
        if self._settings_poller:
            tasks.append(asyncio.create_task(
                self._settings_poller.run(), name="settings"
            ))

        # Wait for WS, then subscribe
        await asyncio.sleep(2)
        if tickers:
            await self._ws_client.subscribe_markets(tickers)

        self._update_status(is_running=True)
        await self._telegram.send(
            f"Engine started [{self._config.mode.value.upper()}]\n"
            f"Markets: {len(tickers)}\n"
            f"Balance: ${balance / 100:.2f}"
        )

        logger.info("engine.running")
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass
        finally:
            await self._shutdown()

    # ------------------------------------------------------------------
    # Periodic tasks
    # ------------------------------------------------------------------

    async def _snapshot_loop(self) -> None:
        """Write portfolio snapshots at configured interval."""
        while True:
            try:
                await asyncio.sleep(self._config.snapshot_interval_seconds)
                await self._write_snapshot()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("snapshot.error")

    async def _write_snapshot(self) -> None:
        if not self._db:
            return
        balance = await self._executor.get_balance_cents()
        unrealized = self._position_tracker.get_total_unrealized_pnl_cents()
        realized = self._position_tracker.get_total_realized_pnl_cents()
        positions = self._position_tracker.get_all_positions()
        self._db.log_portfolio_snapshot(
            balance_cents=balance,
            equity_cents=balance + unrealized,
            open_pnl_cents=unrealized,
            realized_pnl_cents=realized,
            num_positions=len(positions),
            num_open_orders=self._quoter.resting_order_count
            if hasattr(self._quoter, "resting_order_count") else 0,
            mode=self._config.mode,
        )

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    async def _on_fill(self, event: FillEvent) -> None:
        fill = event.fill
        if self._db:
            self._db.log_fill(fill, self._config.mode)
        await self._telegram.send_fill_alert(format_fill(fill))

    async def _on_connection_lost(self, event: ConnectionLost) -> None:
        logger.warning("engine.connection_lost", reason=event.reason)
        await self._quoter.cancel_all_quotes()
        await self._executor.cancel_all()
        await self._telegram.send_connection_status(False, event.reason)

    async def _on_connection_restored(self, event: ConnectionRestored) -> None:
        logger.info("engine.connection_restored")
        self._circuit_breakers.reset_connection()
        await self._telegram.send_connection_status(True)

    async def _on_market_resolved(self, event: MarketResolved) -> None:
        logger.info("engine.market_resolved", ticker=event.ticker)
        self._quoter.pause_market(event.ticker)
        self._orderbook_mgr.remove(event.ticker)

    async def _on_market_paused(self, event: MarketPaused) -> None:
        logger.info("engine.market_paused", ticker=event.ticker)
        self._quoter.pause_market(event.ticker)

    async def _on_market_resumed(self, event: MarketResumed) -> None:
        logger.info("engine.market_resumed", ticker=event.ticker)
        self._quoter.resume_market(event.ticker)

    async def _on_config_changed(self, event: ConfigChanged) -> None:
        logger.info("engine.config_changed", keys=event.changed_keys)

    # ------------------------------------------------------------------
    # Telegram command callbacks
    # ------------------------------------------------------------------

    async def _handle_pause(self) -> None:
        self._paused = True
        await self._quoter.cancel_all_quotes()
        logger.info("engine.paused_by_user")

    async def _handle_resume(self) -> None:
        self._paused = False
        self._circuit_breakers.reset_all()
        logger.info("engine.resumed_by_user")

    async def _handle_get_status(self) -> str:
        balance = await self._executor.get_balance_cents()
        positions = self._position_tracker.get_all_positions()
        return (
            f"Mode: {self._config.mode.value.upper()}\n"
            f"Connected: {self._ws_client.is_connected}\n"
            f"Paused: {self._paused}\n"
            f"Halted: {self._risk.is_halted}\n"
            f"Balance: ${balance / 100:.2f}\n"
            f"Positions: {len(positions)}\n"
            f"Markets: {len(self._scanner.selected_tickers)}"
        )

    async def _handle_get_risk(self) -> str:
        summary = self._risk.get_risk_summary()
        breakers = self._circuit_breakers.get_status()
        return format_risk_summary(summary) + "\n\n" + format_breaker_status(breakers)

    async def _handle_get_positions(self) -> str:
        positions = self._position_tracker.get_all_positions()
        return format_positions(positions)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    async def _shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        logger.info("engine.shutting_down")

        cancelled = await self._quoter.cancel_all_quotes()
        cancelled += await self._executor.cancel_all()
        logger.info("engine.orders_cancelled", count=cancelled)

        self._update_status(is_running=False)
        await self._telegram.send("Engine stopped")

        if self._db:
            await self._db.flush()
            await self._db.close()
        await self._ws_client.stop()
        await self._rest_client.close()
        logger.info("engine.stopped")

    def _update_status(self, is_running: bool) -> None:
        if not self._db:
            return
        breakers = self._circuit_breakers.get_status()
        cb_state = "ok"
        cb_reason = None
        for b in breakers:
            if b.state.value == "halted":
                cb_state = "halted"
                cb_reason = b.reason
                break
            if b.state.value == "warning":
                cb_state = "warning"

        self._db.update_engine_status(
            mode=self._config.mode,
            is_running=is_running,
            is_paused=self._paused,
            connected=self._ws_client.is_connected,
            active_markets=self._scanner.selected_tickers,
            circuit_breaker_state=cb_state,
            circuit_breaker_reason=cb_reason,
        )

    @property
    def resting_order_count(self) -> int:
        return len(self._quoter.active_markets) * 2


def _setup_signals(engine: Engine, loop: asyncio.AbstractEventLoop) -> None:
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(engine._shutdown()))


async def main() -> None:
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(0))
    engine = Engine()
    loop = asyncio.get_running_loop()
    try:
        _setup_signals(engine, loop)
    except NotImplementedError:
        pass
    await engine.run()


if __name__ == "__main__":
    asyncio.run(main())
