#!/usr/bin/env python3
"""
Seed default bot_settings row into the database.

Run after Prisma migration: python3 scripts/seed_settings.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv


async def seed():
    load_dotenv("engine/.env")
    url = os.getenv("DATABASE_URL", "")
    if not url:
        print("DATABASE_URL not set")
        sys.exit(1)

    import asyncpg
    conn = await asyncpg.connect(url)

    # Check if settings exist
    row = await conn.fetchrow("SELECT id FROM bot_settings WHERE id = 'singleton'")
    if row:
        print("bot_settings already seeded")
        await conn.close()
        return

    await conn.execute("""
        INSERT INTO bot_settings (
            id, mode,
            "maxPositionPerMarket", "globalExposureLimitCents",
            "dailyLossLimitCents", "drawdownLimit",
            "baseGamma", sigma, "minSpreadCents", "orderSize", "signalWeight",
            "minVolume", "maxMarketSpreadCents", "minTimeToExpiry",
            "paperMilestoneDays",
            "settingsPollIntervalSec", "reconciliationIntervalSec", "snapshotIntervalSec",
            "updatedAt"
        ) VALUES (
            'singleton', 'paper',
            10, 10000,
            1000, 0.10,
            0.3, 0.15, 3, 5, 0.0,
            100, 10, 3600,
            30,
            5, 30, 300,
            NOW()
        )
    """)
    print("bot_settings seeded with defaults")

    # Seed engine_status
    await conn.execute("""
        INSERT INTO engine_status (
            id, mode, "isRunning", "isPaused", connected,
            "activeMarkets", "circuitBreakerState", "lastHeartbeatAt"
        ) VALUES (
            'singleton', 'paper', false, false, false,
            '[]', 'ok', NOW()
        )
        ON CONFLICT (id) DO NOTHING
    """)
    print("engine_status seeded")

    # Seed paper_milestone
    await conn.execute("""
        INSERT INTO paper_milestone (
            id, "startedAt", "targetDays", "profitableDays",
            achieved
        ) VALUES (
            'singleton', NOW(), 30, 0, false
        )
        ON CONFLICT (id) DO NOTHING
    """)
    print("paper_milestone seeded")

    await conn.close()
    print("Done!")


if __name__ == "__main__":
    asyncio.run(seed())
