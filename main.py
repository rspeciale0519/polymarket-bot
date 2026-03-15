#!/usr/bin/env python3
"""
Polymarket Copy-Trading Bot
Main entry point and monitor loop
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import List, Optional

from dotenv import load_dotenv

from api_client import PolymarketClient, PolymarketDataClient
from trader_monitor import TraderMonitor
from trading_engine import TradingEngine
from telegram_notifier import TelegramNotifier
from storage import Storage

# Load environment
load_dotenv()

# Configure logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class PolymarketBot:
    def __init__(self):
        self.dry_run = os.getenv("DRY_RUN", "false").lower() == "true"
        self.poll_interval = int(os.getenv("POLL_INTERVAL_SECONDS", "300"))
        self.report_interval = int(os.getenv("REPORT_INTERVAL_MINUTES", "60"))
        self.last_report = datetime.now()
        
        # Initialize clients
        self.data_client = PolymarketDataClient(
            host=os.getenv("DATA_API_HOST")
        )
        
        self.clob_client = PolymarketClient(
            private_key=os.getenv("PRIVATE_KEY"),
            wallet_address=os.getenv("WALLET_ADDRESS"),
            chain_id=int(os.getenv("POLYMARKET_CHAIN_ID", "137")),
            host=os.getenv("POLYMARKET_HOST"),
            dry_run=self.dry_run
        )
        
        # Initialize modules
        self.trader_monitor = TraderMonitor(self.data_client)
        self.trading_engine = TradingEngine(self.clob_client, self.dry_run)
        self.notifier = TelegramNotifier(
            token=os.getenv("TELEGRAM_TOKEN"),
            chat_id=os.getenv("TELEGRAM_CHAT_ID")
        )
        self.storage = Storage("trades.db")
        
        # Initialize portfolio tracking
        self.initial_capital = float(os.getenv("CAPITAL", "100"))
        self.current_equity = self.initial_capital
        
        logger.info(f"Bot initialized. Dry run: {self.dry_run}")
    
    async def run(self):
        """Main monitoring loop"""
        logger.info("Starting monitor loop...")
        
        try:
            while True:
                try:
                    await self._iteration()
                except Exception as e:
                    logger.error(f"Error in iteration: {e}", exc_info=True)
                    await self.notifier.send(f"⚠️ Bot error: {str(e)[:100]}")
                
                await asyncio.sleep(self.poll_interval)
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
            await self._shutdown()
    
    async def _iteration(self):
        """Single monitor iteration"""
        
        # 1. Fetch leaderboard
        leaderboard = await self.trader_monitor.get_leaderboard(
            limit=5,
            time_period="MONTH"
        )
        
        if not leaderboard:
            logger.warning("No leaderboard data")
            return
        
        logger.info(f"Leaderboard updated: {len(leaderboard)} traders")
        
        # 2. Monitor positions for each trader
        for trader in leaderboard[:5]:  # Top 5
            try:
                await self._monitor_trader(trader)
            except Exception as e:
                logger.error(f"Error monitoring trader {trader.get('proxyWallet')}: {e}")
        
        # 3. Periodic P&L report
        if datetime.now() - self.last_report > timedelta(minutes=self.report_interval):
            await self._send_pnl_report()
            self.last_report = datetime.now()
    
    async def _monitor_trader(self, trader):
        """Monitor a single trader for new positions"""
        
        trader_address = trader.get("proxyWallet")
        if not trader_address:
            return
        
        # Get current positions
        positions = await self.trader_monitor.get_positions(trader_address)
        
        # Detect new positions vs. last known state
        new_positions = await self.trader_monitor.get_new_positions(
            trader_address,
            positions
        )
        
        for position in new_positions:
            logger.info(f"New position detected from {trader.get('userName')}: {position}")
            
            # Check risk controls
            if self.current_equity < 50:
                logger.warning("Insufficient capital, skipping trade")
                continue
            
            # Check max drawdown
            drawdown = (self.current_equity - self.initial_capital) / self.initial_capital
            if drawdown < -float(os.getenv("MAX_DRAWDOWN", "0.10")):
                logger.error(f"Max drawdown reached: {drawdown:.1%}, stopping trades")
                await self.notifier.send(f"🛑 Max drawdown reached: {drawdown:.1%}")
                continue
            
            # Execute copy trade
            trade = await self._execute_copy_trade(position, trader)
            
            if trade:
                self.storage.log_trade(trade)
                await self.notifier.send(
                    f"📊 COPY: {position.get('title', 'Market')} "
                    f"({position.get('side', 'BUY')} @ {position.get('price', 0.50)}) "
                    f"Size: {trade.get('size')} | Capital: ${self.current_equity:.2f}"
                )
    
    async def _execute_copy_trade(self, position, trader):
        """Execute a copy trade for a detected position"""
        
        try:
            # Calculate position size
            max_position = float(os.getenv("MAX_POSITION_SIZE", "50"))
            size = await self.trading_engine.calculate_copy_size(
                position,
                self.current_equity,
                max_position
            )
            
            if size < 1:
                logger.info(f"Position too small to copy: {size}")
                return None
            
            # Check liquidity
            spread_ok = await self.trading_engine.check_liquidity(
                position.get("token_id"),
                max_spread=float(os.getenv("MIN_LIQUIDITY_SPREAD", "0.05"))
            )
            
            if not spread_ok:
                logger.warning(f"Spread too wide, skipping: {position.get('token_id')}")
                return None
            
            # Place order
            order = await self.trading_engine.place_order(
                token_id=position.get("token_id"),
                price=position.get("price", 0.50),
                size=size,
                side=position.get("side", "BUY"),
                order_type="GTC"
            )
            
            if order:
                logger.info(f"Trade executed: {order}")
                self.current_equity -= (size * position.get("price", 0.50))
                return order
            
            return None
        
        except Exception as e:
            logger.error(f"Error executing copy trade: {e}", exc_info=True)
            return None
    
    async def _send_pnl_report(self):
        """Send hourly P&L report"""
        
        try:
            trades = self.storage.get_recent_trades(hours=1)
            total_pnl = sum(t.get("pnl", 0) for t in trades)
            return_pct = total_pnl / self.initial_capital * 100 if self.initial_capital else 0
            
            report = (
                f"📈 **Hourly P&L Report**\n"
                f"P&L: ${total_pnl:+.2f} ({return_pct:+.1f}%)\n"
                f"Equity: ${self.current_equity:.2f}\n"
                f"Trades: {len(trades)}\n"
                f"Mode: {'🔧 DRY RUN' if self.dry_run else '🟢 LIVE'}"
            )
            
            await self.notifier.send(report)
            logger.info(f"Report sent: P&L ${total_pnl:+.2f}")
        
        except Exception as e:
            logger.error(f"Error sending report: {e}")
    
    async def _shutdown(self):
        """Cleanup on exit"""
        logger.info("Shutting down...")
        await self.notifier.send("👋 Bot stopped")


async def main():
    """Entry point"""
    bot = PolymarketBot()
    
    if os.getenv("DRY_RUN", "false").lower() == "true":
        logger.info("🔧 Running in DRY RUN mode - no real trades will execute")
        await bot.notifier.send("🔧 Bot started in DRY RUN mode")
    else:
        logger.warning("🟢 Running in LIVE mode - TRADES WILL EXECUTE")
        await bot.notifier.send("🟢 Bot started in LIVE mode - TRADING ACTIVE")
    
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
