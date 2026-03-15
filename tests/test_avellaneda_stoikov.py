"""Tests for the Avellaneda-Stoikov model."""

import math

from engine.strategy.avellaneda_stoikov import (
    compute_dynamic_gamma,
    compute_inventory_skew,
    compute_optimal_spread,
    compute_quotes,
    compute_reservation_price,
)


class TestReservationPrice:
    def test_flat_inventory_equals_mid(self):
        """Zero inventory → reservation = mid."""
        r = compute_reservation_price(50.0, 0.0, 0.3, 0.15, 0.5)
        assert abs(r - 50.0) < 0.01

    def test_long_inventory_lowers_reservation(self):
        """Long position → reservation drops below mid (wants to sell)."""
        r = compute_reservation_price(50.0, 0.5, 0.3, 0.15, 0.5)
        assert r < 50.0

    def test_short_inventory_raises_reservation(self):
        """Short position → reservation rises above mid (wants to buy)."""
        r = compute_reservation_price(50.0, -0.5, 0.3, 0.15, 0.5)
        assert r > 50.0

    def test_more_inventory_more_skew(self):
        """Higher inventory ratio → larger skew from mid."""
        r_small = compute_reservation_price(50.0, 0.2, 0.3, 0.15, 0.5)
        r_large = compute_reservation_price(50.0, 0.8, 0.3, 0.15, 0.5)
        # Both below mid, but r_large should be further below
        assert r_large < r_small < 50.0

    def test_time_remaining_zero_no_skew(self):
        """At expiry, time_remaining=0 → no inventory skew."""
        r = compute_reservation_price(50.0, 0.8, 0.3, 0.15, 0.0)
        assert abs(r - 50.0) < 0.01


class TestOptimalSpread:
    def test_positive_spread(self):
        spread = compute_optimal_spread(0.3, 0.15, 0.5, 1.5)
        assert spread > 0

    def test_higher_gamma_wider_spread(self):
        s_low = compute_optimal_spread(0.1, 0.15, 0.5, 1.5)
        s_high = compute_optimal_spread(0.5, 0.15, 0.5, 1.5)
        assert s_high > s_low

    def test_higher_sigma_wider_spread(self):
        s_low = compute_optimal_spread(0.3, 0.05, 0.5, 1.5)
        s_high = compute_optimal_spread(0.3, 0.25, 0.5, 1.5)
        assert s_high > s_low

    def test_time_zero_minimal_spread(self):
        s = compute_optimal_spread(0.3, 0.15, 0.0, 1.5)
        # Inventory component is 0, only arrival component remains
        assert s > 0
        s_half = compute_optimal_spread(0.3, 0.15, 0.5, 1.5)
        assert s < s_half


class TestDynamicGamma:
    def test_flat_inventory_returns_base(self):
        g = compute_dynamic_gamma(0.3, 0.0)
        assert g == 0.3

    def test_full_inventory_quadruples(self):
        """At max inventory, gamma should be 5x base (1 + 4*1^2)."""
        g = compute_dynamic_gamma(0.3, 1.0, scale_factor=4.0)
        assert abs(g - 0.3 * 5) < 0.01

    def test_half_inventory(self):
        """At 50% inventory, gamma = base * (1 + 4*0.25) = base * 2."""
        g = compute_dynamic_gamma(0.3, 0.5, scale_factor=4.0)
        assert abs(g - 0.3 * 2) < 0.01

    def test_negative_inventory_same_as_positive(self):
        g_pos = compute_dynamic_gamma(0.3, 0.7)
        g_neg = compute_dynamic_gamma(0.3, -0.7)
        assert abs(g_pos - g_neg) < 0.01


class TestInventorySkew:
    def test_flat_inventory_symmetric(self):
        bid_s, ask_s = compute_inventory_skew(0.0, 2.0)
        assert abs(bid_s - ask_s) < 0.01

    def test_long_widens_ask(self):
        bid_s, ask_s = compute_inventory_skew(0.5, 2.0)
        assert ask_s > bid_s

    def test_short_widens_bid(self):
        bid_s, ask_s = compute_inventory_skew(-0.5, 2.0)
        assert bid_s > ask_s

    def test_both_positive(self):
        bid_s, ask_s = compute_inventory_skew(0.8, 2.0)
        assert bid_s > 0
        assert ask_s > 0


class TestComputeQuotes:
    def test_basic_quotes(self):
        bid, ask, fv = compute_quotes(
            mid_price=50.0, inventory_ratio=0.0, gamma=0.3,
            sigma=0.15, time_remaining=0.5, kappa=1.5,
            min_spread_cents=3,
        )
        assert 1 <= bid < ask <= 99
        assert ask - bid >= 3  # min spread enforced

    def test_quotes_within_bounds(self):
        for mid in [5, 50, 95]:
            bid, ask, fv = compute_quotes(
                mid_price=float(mid), inventory_ratio=0.0, gamma=0.3,
                sigma=0.15, time_remaining=0.5, kappa=1.5,
                min_spread_cents=3,
            )
            assert 1 <= bid
            assert ask <= 99
            assert ask > bid

    def test_long_inventory_skews_quotes_down(self):
        _, _, fv_flat = compute_quotes(
            50.0, 0.0, 0.3, 0.15, 0.5, 1.5, 3,
        )
        _, _, fv_long = compute_quotes(
            50.0, 0.7, 0.3, 0.15, 0.5, 1.5, 3,
        )
        assert fv_long < fv_flat

    def test_signal_skew_shifts_quotes(self):
        bid_no_signal, ask_no_signal, _ = compute_quotes(
            50.0, 0.0, 0.3, 0.15, 0.5, 1.5, 3, signal_skew=0.0,
        )
        bid_bull, ask_bull, _ = compute_quotes(
            50.0, 0.0, 0.3, 0.15, 0.5, 1.5, 3, signal_skew=3.0,
        )
        assert bid_bull >= bid_no_signal
        assert ask_bull >= ask_no_signal

    def test_spread_multiplier_widens(self):
        bid_normal, ask_normal, _ = compute_quotes(
            50.0, 0.0, 0.3, 0.15, 0.5, 1.5, 3, spread_multiplier=1.0,
        )
        bid_wide, ask_wide, _ = compute_quotes(
            50.0, 0.0, 0.3, 0.15, 0.5, 1.5, 3, spread_multiplier=2.0,
        )
        spread_normal = ask_normal - bid_normal
        spread_wide = ask_wide - bid_wide
        assert spread_wide >= spread_normal

    def test_min_spread_enforced(self):
        bid, ask, _ = compute_quotes(
            50.0, 0.0, 0.01, 0.01, 0.01, 100.0, 5,
        )
        assert ask - bid >= 5
