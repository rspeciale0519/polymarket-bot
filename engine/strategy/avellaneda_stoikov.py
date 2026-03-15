"""
Avellaneda-Stoikov market making model adapted for binary prediction markets.

Binary markets are bounded [1, 99] cents with resolution jumps.
This adaptation uses:
- Dynamic gamma that grows quadratically with inventory concentration
- Time-weighted inventory penalty (decays as expiry approaches)
- Spread floor to prevent unprofitable quoting

All functions are pure — no state, no I/O, trivially testable.
"""

from __future__ import annotations

import math


def compute_reservation_price(
    mid_price: float,
    inventory_ratio: float,
    gamma: float,
    sigma: float,
    time_remaining: float,
) -> float:
    """
    Compute the reservation (indifference) price.

    The reservation price is shifted from the midpoint based on inventory.
    Long inventory → lower reservation → more willing to sell.
    Short inventory → higher reservation → more willing to buy.

    Args:
        mid_price: Current market midpoint in cents (1-99).
        inventory_ratio: Net position / max position, range [-1, 1].
            Positive = long YES, negative = short YES.
        gamma: Risk aversion parameter. Higher = wider spreads, faster
            inventory reduction. Start with 0.3.
        sigma: Estimated price volatility (fraction, e.g. 0.15 = 15%).
        time_remaining: Fraction of time until expiry, range [0, 1].
            1.0 = just opened, 0.0 = about to expire.

    Returns:
        Reservation price in cents (float, not yet rounded).
    """
    # Scale sigma to cents for the calculation
    sigma_cents = sigma * 100.0

    skew = inventory_ratio * gamma * (sigma_cents ** 2) * time_remaining
    reservation = mid_price - skew

    return reservation


def compute_optimal_spread(
    gamma: float,
    sigma: float,
    time_remaining: float,
    kappa: float,
) -> float:
    """
    Compute the optimal bid-ask spread (Avellaneda-Stoikov).

    spread = gamma * sigma^2 * T + (2/gamma) * ln(1 + gamma/kappa)

    Args:
        gamma: Risk aversion parameter.
        sigma: Estimated price volatility (fraction).
        time_remaining: Fraction of time until expiry [0, 1].
        kappa: Order arrival rate intensity. Higher = more frequent fills.
            Estimate from recent trade volume. Start with 1.5.

    Returns:
        Optimal spread in cents (float).
    """
    sigma_cents = sigma * 100.0

    inventory_component = gamma * (sigma_cents ** 2) * time_remaining
    arrival_component = (2.0 / max(gamma, 0.001)) * math.log(
        1.0 + gamma / max(kappa, 0.001)
    )

    return inventory_component + arrival_component


def compute_dynamic_gamma(
    base_gamma: float,
    inventory_ratio: float,
    scale_factor: float = 4.0,
) -> float:
    """
    Dynamic gamma that increases quadratically with inventory concentration.

    As inventory builds up, gamma increases, which simultaneously:
    - Widens the spread (more cautious)
    - Shifts reservation price more aggressively toward reducing inventory

    Args:
        base_gamma: Base risk aversion (e.g. 0.3).
        inventory_ratio: abs(net_position / max_position), range [0, 1].
        scale_factor: How aggressively gamma grows. 4.0 means gamma
            quadruples at max inventory.

    Returns:
        Effective gamma (always >= base_gamma).
    """
    ratio_clamped = min(abs(inventory_ratio), 1.0)
    return base_gamma * (1.0 + scale_factor * ratio_clamped ** 2)


def compute_inventory_skew(
    inventory_ratio: float,
    half_spread: float,
    skew_intensity: float = 3.0,
) -> tuple[float, float]:
    """
    Compute asymmetric bid/ask spread adjustment based on inventory.

    Long inventory → tighten bid (attract buys from us), widen ask.
    Short inventory → widen bid, tighten ask (attract sells to us).

    Args:
        inventory_ratio: net_position / max_position, range [-1, 1].
        half_spread: Half of the optimal spread in cents.
        skew_intensity: How strongly to skew. 3.0 is moderate.

    Returns:
        (bid_spread, ask_spread) — distances from reservation price.
        Both are positive. bid_price = reservation - bid_spread,
        ask_price = reservation + ask_spread.
    """
    ratio_clamped = max(-1.0, min(1.0, inventory_ratio))
    skew = abs(ratio_clamped) * skew_intensity

    if ratio_clamped > 0:
        # Long: tighten bid (smaller distance), widen ask
        bid_spread = half_spread * max(1.0 - skew, 0.1)
        ask_spread = half_spread * (1.0 + skew)
    elif ratio_clamped < 0:
        # Short: widen bid, tighten ask
        bid_spread = half_spread * (1.0 + skew)
        ask_spread = half_spread * max(1.0 - skew, 0.1)
    else:
        bid_spread = half_spread
        ask_spread = half_spread

    return bid_spread, ask_spread


def compute_quotes(
    mid_price: float,
    inventory_ratio: float,
    gamma: float,
    sigma: float,
    time_remaining: float,
    kappa: float,
    min_spread_cents: int,
    signal_skew: float = 0.0,
    spread_multiplier: float = 1.0,
) -> tuple[int, int, float]:
    """
    Full quote computation pipeline.

    Args:
        mid_price: Current midpoint in cents.
        inventory_ratio: net_position / max_position [-1, 1].
        gamma: Base risk aversion.
        sigma: Price volatility estimate.
        time_remaining: Time fraction until expiry [0, 1].
        kappa: Order arrival rate.
        min_spread_cents: Minimum spread floor.
        signal_skew: Directional signal shift in cents (-5 to +5 typical).
            Positive = bullish (shift quotes up).
        spread_multiplier: Circuit breaker multiplier (1.0 normal, 2.0 widen).

    Returns:
        (bid_price_cents, ask_price_cents, fair_value_cents) all as ints
        except fair_value which is float.
    """
    # Dynamic gamma
    dyn_gamma = compute_dynamic_gamma(gamma, inventory_ratio)

    # Reservation price
    reservation = compute_reservation_price(
        mid_price, inventory_ratio, dyn_gamma, sigma, time_remaining
    )

    # Apply directional signal
    reservation += signal_skew

    # Optimal spread
    raw_spread = compute_optimal_spread(dyn_gamma, sigma, time_remaining, kappa)
    spread = max(raw_spread * spread_multiplier, float(min_spread_cents))
    half_spread = spread / 2.0

    # Inventory skew
    bid_spread, ask_spread = compute_inventory_skew(inventory_ratio, half_spread)

    # Final prices
    bid_price = reservation - bid_spread
    ask_price = reservation + ask_spread

    # Clamp to valid range [1, 99]
    bid_cents = max(1, min(98, int(round(bid_price))))
    ask_cents = max(2, min(99, int(round(ask_price))))

    # Ensure minimum spread
    if ask_cents - bid_cents < min_spread_cents:
        center = (bid_cents + ask_cents) / 2.0
        bid_cents = max(1, int(center - min_spread_cents / 2.0))
        ask_cents = min(99, bid_cents + min_spread_cents)

    return bid_cents, ask_cents, reservation
