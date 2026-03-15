"""
Message formatting helpers for Telegram notifications.
"""

from __future__ import annotations

from engine.core.types import CircuitBreakerState, Fill, InventoryState


def format_pnl(cents: int) -> str:
    """Format P&L in dollars with +/- sign."""
    dollars = cents / 100.0
    if cents >= 0:
        return f"+${dollars:.2f}"
    return f"-${abs(dollars):.2f}"


def format_dollars(cents: int) -> str:
    """Format cents as dollar amount."""
    return f"${cents / 100.0:.2f}"


def format_fill(fill: Fill) -> str:
    """Format a fill notification."""
    pnl_str = ""
    if fill.pnl_cents != 0:
        pnl_str = f"\nP&L: {format_pnl(fill.pnl_cents)}"

    fee_str = f" (fee: {format_dollars(fill.fee_cents)})" if fill.fee_cents else ""
    maker_str = "Maker" if fill.is_maker else "Taker"

    return (
        f"{'BUY' if fill.action.value == 'buy' else 'SELL'} "
        f"{fill.count}x {fill.side.value.upper()} @ "
        f"{format_dollars(fill.price_cents)}{fee_str}\n"
        f"Market: {fill.ticker}\n"
        f"Type: {maker_str}{pnl_str}"
    )


def format_positions(positions: list[InventoryState]) -> str:
    """Format position summary for Telegram."""
    if not positions:
        return "No open positions"

    lines = []
    total_unrealized = 0
    total_realized = 0

    for inv in positions:
        if inv.is_flat:
            continue
        direction = "LONG" if inv.is_long else "SHORT"
        lines.append(
            f"  {inv.ticker}: {direction} {abs(inv.net_position)} "
            f"(uPnL: {format_pnl(inv.unrealized_pnl_cents)}, "
            f"rPnL: {format_pnl(inv.realized_pnl_cents)})"
        )
        total_unrealized += inv.unrealized_pnl_cents
        total_realized += inv.realized_pnl_cents

    if not lines:
        return "No open positions"

    header = f"Open Positions ({len(lines)}):"
    footer = (
        f"\nTotal uPnL: {format_pnl(total_unrealized)} | "
        f"rPnL: {format_pnl(total_realized)}"
    )
    return header + "\n" + "\n".join(lines) + footer


def format_risk_summary(summary: dict) -> str:
    """Format risk summary for Telegram /risk command."""
    halted_str = "HALTED" if summary.get("halted") else "OK"
    return (
        f"Risk Status: {halted_str}\n"
        f"Daily P&L: {format_pnl(summary.get('daily_pnl_cents', 0))} "
        f"/ limit: {format_pnl(-summary.get('daily_limit_cents', 0))}\n"
        f"Exposure: {format_dollars(summary.get('total_exposure_cents', 0))} "
        f"/ limit: {format_dollars(summary.get('exposure_limit_cents', 0))}\n"
        f"Positions: {summary.get('active_positions', 0)} "
        f"(max/market: {summary.get('max_position_per_market', 0)})"
    )


def format_daily_report(
    balance_cents: int,
    daily_pnl_cents: int,
    total_pnl_cents: int,
    num_fills: int,
    num_positions: int,
    mode: str,
) -> str:
    """Format daily P&L report."""
    mode_emoji = "PAPER" if mode == "paper" else "LIVE"
    return (
        f"Daily Report [{mode_emoji}]\n"
        f"Balance: {format_dollars(balance_cents)}\n"
        f"Today P&L: {format_pnl(daily_pnl_cents)}\n"
        f"All-Time P&L: {format_pnl(total_pnl_cents)}\n"
        f"Fills Today: {num_fills}\n"
        f"Open Positions: {num_positions}"
    )


def format_breaker_status(statuses: list) -> str:
    """Format circuit breaker status."""
    lines = []
    for s in statuses:
        icon = {
            CircuitBreakerState.OK: "OK",
            CircuitBreakerState.WARNING: "WARN",
            CircuitBreakerState.HALTED: "HALT",
        }.get(s.state, "?")
        detail = f" ({s.reason})" if s.reason else ""
        lines.append(f"  {s.name}: {icon}{detail}")
    return "Circuit Breakers:\n" + "\n".join(lines)
