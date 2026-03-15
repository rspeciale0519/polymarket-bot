"""
Backtest simulation runner.

Replays historical data through the event bus, using the BacktestExecutor
for fills. Computes summary statistics at the end of the run.
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime

import structlog

from engine.backtest.data_loader import DataLoader, HistoricalDataset, HistoricalTick
from engine.core.event_bus import EventBus
from engine.core.types import EngineConfig, OrderbookUpdate
from engine.execution.backtest_executor import BacktestExecutor
from engine.risk.risk_engine import RiskEngine
from engine.strategy.avellaneda_stoikov import compute_quotes
from engine.strategy.inventory_manager import InventoryManager
from engine.strategy.signal_integrator import SignalIntegrator

logger = structlog.get_logger(__name__)


@dataclass
class BacktestResult:
    """Summary statistics from a backtest run."""
    ticker: str
    start_time: datetime | None = None
    end_time: datetime | None = None
    duration_hours: float = 0.0
    total_ticks: int = 0
    total_fills: int = 0
    total_fees_cents: int = 0
    net_pnl_cents: int = 0
    starting_balance_cents: int = 0
    ending_balance_cents: int = 0
    return_pct: float = 0.0
    max_drawdown_cents: int = 0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    fill_rate: float = 0.0
    equity_curve: list[tuple[datetime, int]] = field(default_factory=list)


class BacktestRunner:
    """Runs backtests by replaying historical data."""

    def __init__(
        self,
        config: EngineConfig,
        bus: EventBus,
        executor: BacktestExecutor,
        risk_engine: RiskEngine,
        inventory_mgr: InventoryManager,
        signal_integrator: SignalIntegrator,
    ) -> None:
        self._config = config
        self._bus = bus
        self._executor = executor
        self._risk = risk_engine
        self._inventory = inventory_mgr
        self._signals = signal_integrator

    async def run(self, dataset: HistoricalDataset) -> BacktestResult:
        """Run a backtest on a historical dataset."""
        logger.info(
            "backtest.starting",
            ticker=dataset.ticker,
            ticks=len(dataset.ticks),
            duration_hours=dataset.duration_hours,
        )

        starting_balance = await self._executor.get_balance_cents()
        quote_count = 0

        for tick in dataset.ticks:
            self._executor.set_virtual_time(tick.timestamp)

            # Create orderbook from tick
            book = tick.to_orderbook()

            # Check for fills against current resting orders
            await self._executor.process_orderbook_tick(tick.ticker, book)

            # Publish orderbook update (triggers quote generation via bus)
            await self._bus.publish(
                OrderbookUpdate(ticker=tick.ticker, orderbook=book)
            )

            # Allow event handlers to process
            await self._bus.drain()
            quote_count += 1

        # Final cleanup — cancel remaining orders
        await self._executor.cancel_all()

        # Compute results
        result = self._compute_results(dataset, starting_balance)

        logger.info(
            "backtest.complete",
            ticker=dataset.ticker,
            fills=result.total_fills,
            pnl=result.net_pnl_cents,
            return_pct=f"{result.return_pct:.2f}%",
            max_dd=f"{result.max_drawdown_pct:.2f}%",
            sharpe=f"{result.sharpe_ratio:.2f}",
        )

        return result

    def _compute_results(
        self,
        dataset: HistoricalDataset,
        starting_balance: int,
    ) -> BacktestResult:
        ending_balance = self._executor._balance_cents
        net_pnl = ending_balance - starting_balance

        return_pct = (net_pnl / starting_balance * 100) if starting_balance else 0.0

        equity_curve = self._executor.get_equity_curve()

        max_dd_cents, max_dd_pct = _compute_max_drawdown(equity_curve)
        sharpe = _compute_sharpe(equity_curve)

        fill_rate = (
            self._executor.total_fills / max(len(dataset.ticks), 1)
        ) if dataset.ticks else 0.0

        return BacktestResult(
            ticker=dataset.ticker,
            start_time=dataset.start_time,
            end_time=dataset.end_time,
            duration_hours=dataset.duration_hours,
            total_ticks=len(dataset.ticks),
            total_fills=self._executor.total_fills,
            total_fees_cents=self._executor.total_fees_cents,
            net_pnl_cents=net_pnl,
            starting_balance_cents=starting_balance,
            ending_balance_cents=ending_balance,
            return_pct=return_pct,
            max_drawdown_cents=max_dd_cents,
            max_drawdown_pct=max_dd_pct,
            sharpe_ratio=sharpe,
            fill_rate=fill_rate,
            equity_curve=equity_curve,
        )


def _compute_max_drawdown(
    equity_curve: list[tuple[datetime, int]],
) -> tuple[int, float]:
    """Compute max drawdown in cents and percentage."""
    if len(equity_curve) < 2:
        return 0, 0.0

    peak = equity_curve[0][1]
    max_dd_cents = 0
    max_dd_pct = 0.0

    for _, balance in equity_curve:
        if balance > peak:
            peak = balance
        dd = peak - balance
        if dd > max_dd_cents:
            max_dd_cents = dd
            max_dd_pct = (dd / peak * 100) if peak > 0 else 0.0

    return max_dd_cents, max_dd_pct


def _compute_sharpe(
    equity_curve: list[tuple[datetime, int]],
    risk_free_rate: float = 0.0,
) -> float:
    """Compute approximate Sharpe ratio from equity curve."""
    if len(equity_curve) < 3:
        return 0.0

    returns = []
    for i in range(1, len(equity_curve)):
        prev = equity_curve[i - 1][1]
        curr = equity_curve[i][1]
        if prev > 0:
            returns.append((curr - prev) / prev)

    if not returns:
        return 0.0

    mean_return = sum(returns) / len(returns)
    variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
    std_dev = math.sqrt(variance) if variance > 0 else 0.0

    if std_dev == 0:
        return 0.0

    return (mean_return - risk_free_rate) / std_dev
