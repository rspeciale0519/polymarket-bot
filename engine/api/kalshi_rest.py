"""
Async Kalshi REST API client (v2).

Single httpx.AsyncClient with connection pooling, signed requests,
and retry logic for rate limits and transient errors.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
import structlog
from cryptography.hazmat.primitives.asymmetric import rsa

from engine.api.auth import build_auth_headers, load_private_key
from engine.core.types import (
    Action,
    Fill,
    InventoryState,
    MarketInfo,
    OrderAck,
    OrderRequest,
    Side,
)

logger = structlog.get_logger(__name__)

MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 1.0


class KalshiRestClient:
    """Async REST client for the Kalshi v2 API."""

    def __init__(
        self,
        base_url: str,
        api_key_id: str,
        private_key_path: str,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key_id = api_key_id
        self._private_key: rsa.RSAPrivateKey | None = None
        self._private_key_path = private_key_path
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        if self._private_key_path:
            self._private_key = load_private_key(self._private_key_path)
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(10.0, connect=5.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()

    # ------------------------------------------------------------------
    # Internal request helpers
    # ------------------------------------------------------------------

    def _auth_headers(self, method: str, path: str) -> dict[str, str]:
        if not self._private_key:
            return {}
        return build_auth_headers(
            self.api_key_id, self._private_key, method, path
        )

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        authenticated: bool = True,
    ) -> dict[str, Any]:
        assert self._client is not None, "Client not started. Call start() first."

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if authenticated:
            headers.update(self._auth_headers(method, path))

        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = await self._client.request(
                    method, path, params=params, json=json_body, headers=headers
                )

                if resp.status_code == 429:
                    wait = RETRY_BACKOFF_BASE * (2 ** attempt)
                    logger.warning("kalshi.rate_limited", wait=wait, attempt=attempt)
                    await asyncio.sleep(wait)
                    # Re-sign with fresh timestamp
                    if authenticated:
                        headers.update(self._auth_headers(method, path))
                    continue

                if resp.status_code >= 500:
                    wait = RETRY_BACKOFF_BASE * (2 ** attempt)
                    logger.warning("kalshi.server_error", status=resp.status_code)
                    await asyncio.sleep(wait)
                    if authenticated:
                        headers.update(self._auth_headers(method, path))
                    continue

                resp.raise_for_status()
                if resp.status_code == 204:
                    return {}
                return resp.json()

            except httpx.HTTPStatusError as e:
                logger.error("kalshi.http_error", status=e.response.status_code,
                             body=e.response.text[:200])
                raise
            except httpx.RequestError as e:
                last_error = e
                logger.warning("kalshi.request_error", error=str(e), attempt=attempt)
                await asyncio.sleep(RETRY_BACKOFF_BASE * (2 ** attempt))

        raise last_error or RuntimeError("Max retries exceeded")

    # ------------------------------------------------------------------
    # Market data endpoints (some public, some authenticated)
    # ------------------------------------------------------------------

    async def get_markets(
        self,
        status: str = "open",
        limit: int = 200,
        cursor: str | None = None,
        event_ticker: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"status": status, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        if event_ticker:
            params["event_ticker"] = event_ticker
        return await self._request("GET", "/markets", params=params)

    async def get_market(self, ticker: str) -> dict[str, Any]:
        return await self._request("GET", f"/markets/{ticker}")

    async def get_orderbook(
        self, ticker: str, depth: int = 10
    ) -> dict[str, Any]:
        return await self._request(
            "GET", f"/markets/{ticker}/orderbook",
            params={"depth": depth},
        )

    async def get_trades(
        self,
        ticker: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if ticker:
            params["ticker"] = ticker
        if cursor:
            params["cursor"] = cursor
        return await self._request("GET", "/markets/trades", params=params)

    async def get_exchange_status(self) -> dict[str, Any]:
        return await self._request("GET", "/exchange/status")

    # ------------------------------------------------------------------
    # Portfolio / authenticated endpoints
    # ------------------------------------------------------------------

    async def get_balance(self) -> int:
        data = await self._request("GET", "/portfolio/balance")
        return int(data.get("balance", 0))

    async def get_positions(
        self,
        ticker: str | None = None,
        limit: int = 200,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if ticker:
            params["ticker"] = ticker
        if cursor:
            params["cursor"] = cursor
        return await self._request("GET", "/portfolio/positions", params=params)

    async def get_fills(
        self,
        ticker: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if ticker:
            params["ticker"] = ticker
        if cursor:
            params["cursor"] = cursor
        return await self._request("GET", "/portfolio/fills", params=params)

    async def get_orders(
        self,
        ticker: str | None = None,
        status: str | None = None,
        limit: int = 200,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if ticker:
            params["ticker"] = ticker
        if status:
            params["status"] = status
        if cursor:
            params["cursor"] = cursor
        return await self._request("GET", "/portfolio/orders", params=params)

    # ------------------------------------------------------------------
    # Order management
    # ------------------------------------------------------------------

    async def create_order(self, req: OrderRequest) -> OrderAck:
        body: dict[str, Any] = {
            "ticker": req.ticker,
            "side": req.side.value,
            "action": req.action.value,
            "count": req.count,
            "type": "limit",
        }

        # Set price on the correct side
        if req.side == Side.YES:
            body["yes_price"] = req.price_cents
        else:
            body["no_price"] = req.price_cents

        if req.post_only:
            body["post_only"] = True
        if req.time_in_force:
            body["time_in_force"] = req.time_in_force
        if req.client_order_id:
            body["client_order_id"] = req.client_order_id

        try:
            data = await self._request("POST", "/portfolio/orders", json_body=body)
            order = data.get("order", data)
            return OrderAck(
                order_id=order.get("order_id", ""),
                client_order_id=req.client_order_id,
                status=order.get("status", "unknown"),
                ticker=req.ticker,
                side=req.side,
                action=req.action,
                price_cents=req.price_cents,
                count=req.count,
                remaining_count=int(
                    float(order.get("remaining_count_fp", str(req.count)))
                ),
            )
        except Exception as e:
            return OrderAck(
                order_id="",
                client_order_id=req.client_order_id,
                status="error",
                ticker=req.ticker,
                side=req.side,
                action=req.action,
                price_cents=req.price_cents,
                count=req.count,
                error=str(e),
            )

    async def amend_order(
        self,
        order_id: str,
        new_price_cents: int | None = None,
        new_count: int | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if new_price_cents is not None:
            body["price"] = new_price_cents
        if new_count is not None:
            body["count"] = new_count
        return await self._request(
            "POST", f"/portfolio/orders/{order_id}/amend", json_body=body
        )

    async def cancel_order(self, order_id: str) -> bool:
        try:
            await self._request("DELETE", f"/portfolio/orders/{order_id}")
            return True
        except Exception:
            logger.exception("kalshi.cancel_order_failed", order_id=order_id)
            return False

    async def cancel_all_orders(self) -> int:
        """Cancel all resting orders. Returns count cancelled."""
        cancelled = 0
        cursor: str | None = None
        while True:
            data = await self.get_orders(status="resting", cursor=cursor)
            orders = data.get("orders", [])
            for order in orders:
                oid = order.get("order_id")
                if oid and await self.cancel_order(oid):
                    cancelled += 1
            cursor = data.get("cursor")
            if not cursor or not orders:
                break
        return cancelled

    async def batch_create_orders(
        self, requests: list[OrderRequest]
    ) -> list[OrderAck]:
        """Submit up to 20 orders in a single batch request."""
        if len(requests) > 20:
            raise ValueError("Batch limit is 20 orders")

        items = []
        for req in requests:
            item: dict[str, Any] = {
                "ticker": req.ticker,
                "side": req.side.value,
                "action": req.action.value,
                "count": req.count,
                "type": "limit",
                "client_order_id": req.client_order_id,
            }
            if req.side == Side.YES:
                item["yes_price"] = req.price_cents
            else:
                item["no_price"] = req.price_cents
            if req.post_only:
                item["post_only"] = True
            if req.time_in_force:
                item["time_in_force"] = req.time_in_force
            items.append(item)

        try:
            data = await self._request(
                "POST", "/portfolio/orders/batched", json_body={"orders": items}
            )
            results = data.get("orders", [])
            acks = []
            for i, result in enumerate(results):
                req = requests[i] if i < len(requests) else requests[-1]
                acks.append(OrderAck(
                    order_id=result.get("order_id", ""),
                    client_order_id=req.client_order_id,
                    status=result.get("status", "unknown"),
                    ticker=req.ticker,
                    side=req.side,
                    action=req.action,
                    price_cents=req.price_cents,
                    count=req.count,
                ))
            return acks
        except Exception as e:
            return [
                OrderAck(
                    order_id="", client_order_id=r.client_order_id,
                    status="error", ticker=r.ticker, side=r.side,
                    action=r.action, price_cents=r.price_cents,
                    count=r.count, error=str(e),
                )
                for r in requests
            ]
