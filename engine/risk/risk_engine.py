"""
Central risk engine — pre-trade gate.

Every OrderRequest passes through check() before reaching the executor.
Full implementation in Phase 3. This is a minimal stub for Phase 2.
"""

from __future__ import annotations

from engine.core.types import EngineConfig, OrderRequest, RiskViolation


class RiskEngine:
    def __init__(self, config: EngineConfig) -> None:
        self._config = config

    def check(self, req: OrderRequest) -> list[RiskViolation]:
        """Pre-trade risk check. Returns violations (empty = approved)."""
        # Phase 3 will add: inventory cap, global exposure, daily loss,
        # circuit breaker state checks. For now, approve everything.
        return []
