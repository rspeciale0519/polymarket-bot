"""
Central risk engine — pre-trade gate.

Every OrderRequest passes through check() before reaching the executor.
Returns a list of RiskViolation objects. Empty = approved.
severity="block" rejects that order. severity="halt" stops all quoting.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog

from engine.core.types import (
    Action,
    EngineConfig,
    InventoryState,
    OrderRequest,
    RiskViolation,
)

logger = structlog.get_logger(__name__)


class RiskEngine:
    def __init__(self, config: EngineConfig) -> None:
        self._config = config
        self._positions: dict[str, InventoryState] = {}
        self._daily_realized_pnl_cents: int = 0
        self._daily_reset_date: str = _today_str()
        self._halted: bool = False
        self._halt_reason: str = ""

    def check(self, req: OrderRequest) -> list[RiskViolation]:
        """Pre-trade risk checks. Returns violations (empty = approved)."""
        self._maybe_reset_daily()
        violations: list[RiskViolation] = []

        # 1. Engine halted?
        if self._halted:
            violations.append(RiskViolation(
                rule="engine_halted",
                severity="halt",
                detail=f"Engine halted: {self._halt_reason}",
            ))
            return violations

        # 2. Per-market inventory cap
        inv = self._positions.get(req.ticker)
        current_pos = abs(inv.net_position) if inv else 0
        if req.action == Action.BUY:
            projected = current_pos + req.count
        else:
            projected = current_pos  # sells reduce position
        if projected > self._config.max_position_per_market:
            violations.append(RiskViolation(
                rule="per_market_inventory",
                severity="block",
                detail=(
                    f"{req.ticker}: projected {projected} "
                    f"> max {self._config.max_position_per_market}"
                ),
            ))

        # 3. Global exposure cap
        total_exposure = self._total_exposure_cents()
        new_exposure = req.count * req.price_cents
        if total_exposure + new_exposure > self._config.global_exposure_limit_cents:
            violations.append(RiskViolation(
                rule="global_exposure",
                severity="block",
                detail=(
                    f"Global exposure {total_exposure + new_exposure} "
                    f"> limit {self._config.global_exposure_limit_cents}"
                ),
            ))

        # 4. Per-market P&L stop
        if inv and inv.realized_pnl_cents < -self._config.daily_loss_limit_cents:
            violations.append(RiskViolation(
                rule="per_market_pnl_stop",
                severity="block",
                detail=(
                    f"{req.ticker}: realized P&L {inv.realized_pnl_cents}c "
                    f"below market stop"
                ),
            ))

        # 5. Daily loss limit
        if self._daily_realized_pnl_cents < -self._config.daily_loss_limit_cents:
            violations.append(RiskViolation(
                rule="daily_loss_limit",
                severity="halt",
                detail=(
                    f"Daily realized P&L {self._daily_realized_pnl_cents}c "
                    f"< limit -{self._config.daily_loss_limit_cents}c"
                ),
            ))

        return violations

    # ------------------------------------------------------------------
    # State updates (called by position tracker / circuit breakers)
    # ------------------------------------------------------------------

    def update_position(self, inv: InventoryState) -> None:
        """Update tracked position for a market."""
        self._positions[inv.ticker] = inv

    def add_realized_pnl(self, pnl_cents: int) -> None:
        """Record realized P&L for daily tracking."""
        self._maybe_reset_daily()
        self._daily_realized_pnl_cents += pnl_cents

    def halt(self, reason: str) -> None:
        """Halt all trading."""
        self._halted = True
        self._halt_reason = reason
        logger.warning("risk_engine.halted", reason=reason)

    def resume(self) -> None:
        """Resume trading after halt."""
        self._halted = False
        self._halt_reason = ""
        logger.info("risk_engine.resumed")

    @property
    def is_halted(self) -> bool:
        return self._halted

    @property
    def halt_reason(self) -> str:
        return self._halt_reason

    @property
    def daily_realized_pnl_cents(self) -> int:
        self._maybe_reset_daily()
        return self._daily_realized_pnl_cents

    @property
    def positions(self) -> dict[str, InventoryState]:
        return dict(self._positions)

    def get_risk_summary(self) -> dict:
        """Summary for Telegram /risk command."""
        return {
            "halted": self._halted,
            "halt_reason": self._halt_reason,
            "daily_pnl_cents": self._daily_realized_pnl_cents,
            "daily_limit_cents": self._config.daily_loss_limit_cents,
            "total_exposure_cents": self._total_exposure_cents(),
            "exposure_limit_cents": self._config.global_exposure_limit_cents,
            "active_positions": len([
                p for p in self._positions.values() if not p.is_flat
            ]),
            "max_position_per_market": self._config.max_position_per_market,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _total_exposure_cents(self) -> int:
        total = 0
        for inv in self._positions.values():
            total += abs(inv.net_position) * abs(inv.cost_basis_cents)
        return total

    def _maybe_reset_daily(self) -> None:
        today = _today_str()
        if today != self._daily_reset_date:
            logger.info(
                "risk_engine.daily_reset",
                prev_pnl=self._daily_realized_pnl_cents,
            )
            self._daily_realized_pnl_cents = 0
            self._daily_reset_date = today
            if self._halted and "daily" in self._halt_reason.lower():
                self.resume()


def _today_str() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")
