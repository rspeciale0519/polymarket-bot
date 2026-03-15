#!/usr/bin/env python3
"""
Health check script — verifies all connections and components.

Run: python3 scripts/healthcheck.py
"""

import asyncio
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv


async def check_database() -> bool:
    """Check PostgreSQL connectivity."""
    try:
        import asyncpg
        url = os.getenv("DATABASE_URL", "")
        if not url:
            print("  SKIP: DATABASE_URL not set")
            return True
        conn = await asyncpg.connect(url)
        await conn.execute("SELECT 1")
        await conn.close()
        print("  OK: PostgreSQL connected")
        return True
    except Exception as e:
        print(f"  FAIL: PostgreSQL — {e}")
        return False


async def check_kalshi_api() -> bool:
    """Check Kalshi API connectivity."""
    try:
        import httpx
        env = os.getenv("KALSHI_ENV", "demo")
        if env == "demo":
            url = "https://demo-api.kalshi.co/trade-api/v2/exchange/status"
        else:
            url = "https://api.elections.kalshi.com/trade-api/v2/exchange/status"

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                print(f"  OK: Kalshi API ({env}) reachable")
                return True
            else:
                print(f"  WARN: Kalshi API returned {resp.status_code}")
                return True  # Reachable but may need auth
    except Exception as e:
        print(f"  FAIL: Kalshi API — {e}")
        return False


def check_kalshi_key() -> bool:
    """Check Kalshi API key configuration."""
    key_id = os.getenv("KALSHI_API_KEY_ID", "")
    key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH", "")

    if not key_id:
        print("  WARN: KALSHI_API_KEY_ID not set (needed for live trading)")
        return True
    if not key_path:
        print("  WARN: KALSHI_PRIVATE_KEY_PATH not set")
        return True
    if not os.path.exists(key_path):
        print(f"  FAIL: Key file not found: {key_path}")
        return False

    print("  OK: Kalshi API key configured")
    return True


def check_telegram() -> bool:
    """Check Telegram configuration."""
    token = os.getenv("TELEGRAM_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        print("  SKIP: Telegram not configured (optional)")
        return True

    print("  OK: Telegram configured")
    return True


def check_imports() -> bool:
    """Verify all engine modules import correctly."""
    try:
        from engine.core.types import EngineConfig, Mode
        from engine.core.event_bus import EventBus
        from engine.core.config import load_config
        from engine.api.auth import sign_request
        from engine.api.kalshi_rest import KalshiRestClient
        from engine.market_data.ws_client import KalshiWebSocketClient
        from engine.market_data.orderbook import OrderbookManager
        from engine.market_data.market_scanner import MarketScanner
        from engine.execution.base_executor import ExecutionAdapter
        from engine.execution.paper_executor import PaperExecutor
        from engine.execution.live_executor import LiveExecutor
        from engine.execution.backtest_executor import BacktestExecutor
        from engine.execution.order_reconciler import OrderReconciler
        from engine.strategy.avellaneda_stoikov import compute_quotes
        from engine.strategy.inventory_manager import InventoryManager
        from engine.strategy.signal_integrator import SignalIntegrator
        from engine.strategy.quote_generator import QuoteGenerator
        from engine.risk.risk_engine import RiskEngine
        from engine.risk.position_tracker import PositionTracker
        from engine.risk.circuit_breakers import CircuitBreakerManager
        from engine.notifications.telegram_bot import TelegramNotifier
        from engine.notifications.formatters import format_fill
        from engine.dashboard_bridge.settings_poller import SettingsPoller
        from engine.backtest.data_loader import DataLoader
        from engine.backtest.backtest_runner import BacktestRunner
        print("  OK: All 25 engine modules import successfully")
        return True
    except Exception as e:
        print(f"  FAIL: Import error — {e}")
        return False


async def main():
    load_dotenv("engine/.env")

    print("=== PolyBot Health Check ===")
    print("")

    results = []

    print("[Imports]")
    results.append(check_imports())

    print("[Database]")
    results.append(await check_database())

    print("[Kalshi API]")
    results.append(await check_kalshi_api())

    print("[Kalshi Key]")
    results.append(check_kalshi_key())

    print("[Telegram]")
    results.append(check_telegram())

    print("")
    passed = sum(results)
    total = len(results)
    if all(results):
        print(f"=== All {total} checks passed ===")
    else:
        print(f"=== {passed}/{total} checks passed ===")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
