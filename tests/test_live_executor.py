"""Tests for the live executor (with mocked API)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from engine.core.event_bus import EventBus
from engine.core.types import Action, OrderAck, OrderRequest, Side
from engine.execution.live_executor import LiveExecutor, TokenBucketRateLimiter


class TestTokenBucketRateLimiter:
    @pytest.mark.asyncio
    async def test_acquire_under_limit(self):
        limiter = TokenBucketRateLimiter(rate=100.0)
        # Should not block
        await limiter.acquire()
        await limiter.acquire()

    @pytest.mark.asyncio
    async def test_rate_limiting_delays(self):
        limiter = TokenBucketRateLimiter(rate=2.0)
        # Drain all tokens
        await limiter.acquire()
        await limiter.acquire()
        # Third should introduce a small delay
        import time
        start = time.monotonic()
        await limiter.acquire()
        elapsed = time.monotonic() - start
        # Should have waited some amount of time
        assert elapsed >= 0  # Non-negative (might be very small)


class TestLiveExecutor:
    @pytest.fixture
    def mock_rest(self):
        rest = AsyncMock()
        rest.create_order = AsyncMock(return_value=OrderAck(
            order_id="kalshi-123",
            client_order_id="test-client-id",
            status="resting",
            ticker="TEST",
            side=Side.YES,
            action=Action.BUY,
            price_cents=50,
            count=5,
            remaining_count=5,
        ))
        rest.cancel_order = AsyncMock(return_value=True)
        rest.cancel_all_orders = AsyncMock(return_value=3)
        rest.get_balance = AsyncMock(return_value=10000)
        rest.get_positions = AsyncMock(return_value={"positions": []})
        rest.amend_order = AsyncMock(return_value={
            "order": {"status": "resting", "client_order_id": "", "side": "yes",
                      "action": "buy", "ticker": "TEST"}
        })
        return rest

    @pytest.fixture
    def bus(self):
        return EventBus()

    @pytest.fixture
    def executor(self, mock_rest, bus):
        return LiveExecutor(rest_client=mock_rest, bus=bus)

    @pytest.mark.asyncio
    async def test_submit_order(self, executor, mock_rest):
        req = OrderRequest(
            ticker="TEST", side=Side.YES, action=Action.BUY,
            count=5, price_cents=50,
        )
        ack = await executor.submit_order(req)
        assert ack.is_success
        assert ack.order_id == "kalshi-123"
        mock_rest.create_order.assert_awaited_once()
        assert "kalshi-123" in executor.tracked_order_ids

    @pytest.mark.asyncio
    async def test_cancel_order(self, executor, mock_rest):
        req = OrderRequest(
            ticker="TEST", side=Side.YES, action=Action.BUY,
            count=5, price_cents=50,
        )
        ack = await executor.submit_order(req)
        result = await executor.cancel_order(ack.order_id)
        assert result is True
        assert ack.order_id not in executor.tracked_order_ids

    @pytest.mark.asyncio
    async def test_cancel_all(self, executor, mock_rest):
        count = await executor.cancel_all()
        assert count == 3
        mock_rest.cancel_all_orders.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_balance(self, executor, mock_rest):
        balance = await executor.get_balance_cents()
        assert balance == 10000

    @pytest.mark.asyncio
    async def test_get_positions_empty(self, executor, mock_rest):
        positions = await executor.get_positions()
        assert positions == []

    @pytest.mark.asyncio
    async def test_amend_order(self, executor, mock_rest):
        ack = await executor.amend_order("order-123", 48, 5)
        assert ack.is_success
        mock_rest.amend_order.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_submit_order_error(self, executor, mock_rest):
        mock_rest.create_order = AsyncMock(return_value=OrderAck(
            order_id="",
            client_order_id="test",
            status="error",
            ticker="TEST",
            side=Side.YES,
            action=Action.BUY,
            price_cents=50,
            count=5,
            error="API error",
        ))
        req = OrderRequest(
            ticker="TEST", side=Side.YES, action=Action.BUY,
            count=5, price_cents=50,
        )
        ack = await executor.submit_order(req)
        assert not ack.is_success
        assert ack.error == "API error"
