"""
Trader monitoring: leaderboard tracking, position detection
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class TraderMonitor:
    """Monitor top traders and detect new positions"""
    
    def __init__(self, data_client):
        self.data_client = data_client
        self.trader_positions: Dict[str, List[Dict]] = {}  # Cache of known positions
    
    async def get_leaderboard(
        self,
        limit: int = 10,
        time_period: str = "MONTH",
        category: str = "OVERALL"
    ) -> List[Dict[str, Any]]:
        """Fetch current leaderboard"""
        return await self.data_client.get_leaderboard(
            category=category,
            time_period=time_period,
            order_by="PNL",
            limit=limit
        )
    
    async def get_positions(self, trader_address: str) -> List[Dict[str, Any]]:
        """Fetch current positions for a trader"""
        positions = await self.data_client.get_positions(trader_address, limit=50)
        
        # Enrich position data
        enriched = []
        for pos in positions:
            enriched.append({
                **pos,
                "trader": trader_address,
                "fetched_at": datetime.now().isoformat(),
                "token_id": pos.get("oppositeAsset") or pos.get("asset"),  # Use outcome token ID
                "side": "BUY" if pos.get("size", 0) > 0 else "SELL",
                "price": pos.get("avgPrice", 0.50),
                "title": pos.get("title", "Unknown Market"),
                "market_id": pos.get("conditionId")
            })
        
        return enriched
    
    async def get_new_positions(
        self,
        trader_address: str,
        current_positions: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Detect new positions (not in previous cache)
        
        Returns list of new positions to copy
        """
        
        previous = self.trader_positions.get(trader_address, [])
        previous_ids = {p.get("market_id") for p in previous}
        
        new_positions = [
            p for p in current_positions
            if p.get("market_id") not in previous_ids
        ]
        
        # Update cache
        self.trader_positions[trader_address] = current_positions
        
        if new_positions:
            logger.info(f"Detected {len(new_positions)} new positions for {trader_address}")
            for pos in new_positions:
                logger.info(f"  - {pos.get('title')} ({pos.get('side')} @ {pos.get('price')})")
        
        return new_positions
    
    async def get_trades(self, trader_address: str) -> List[Dict[str, Any]]:
        """Fetch recent trades for a trader (for analysis)"""
        return await self.data_client.get_trades(trader_address, limit=20)
    
    def get_trader_stats(self, trader: Dict[str, Any]) -> Dict[str, Any]:
        """Extract key stats from leaderboard entry"""
        return {
            "address": trader.get("proxyWallet"),
            "name": trader.get("userName"),
            "pnl": trader.get("pnl", 0),
            "volume": trader.get("vol", 0),
            "verified": trader.get("verifiedBadge", False),
            "twitter": trader.get("xUsername", "N/A")
        }
