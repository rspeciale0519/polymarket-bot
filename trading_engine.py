"""
Trading engine: order execution, risk management
"""

import logging
from typing import Optional, Dict, Any
import os

logger = logging.getLogger(__name__)


class TradingEngine:
    """Execute trades with risk controls"""
    
    def __init__(self, clob_client, dry_run: bool = True):
        self.clob_client = clob_client
        self.dry_run = dry_run
        self.max_position = float(os.getenv("MAX_POSITION_SIZE", "50"))
        self.max_positions = int(os.getenv("MAX_POSITIONS", "3"))
    
    async def calculate_copy_size(
        self,
        position: Dict[str, Any],
        current_equity: float,
        max_position: float
    ) -> float:
        """
        Calculate position size for copy trade
        
        Scales trader's position based on our capital
        """
        
        try:
            trader_size = position.get("size", 0)
            trader_price = position.get("price", 0.50)
            
            if trader_size <= 0:
                return 0
            
            # Assume trader is risking ~5% of capital per trade
            trader_risk_pct = 0.05
            trader_capital_estimate = (trader_size * trader_price) / trader_risk_pct
            
            # Scale to our capital
            scale = current_equity / max(trader_capital_estimate, 1)
            our_position_value = trader_size * trader_price * scale
            
            # Cap at max position
            capped_value = min(our_position_value, max_position)
            
            # Calculate tokens to buy
            tokens = capped_value / max(trader_price, 0.01)
            
            logger.info(
                f"Copy size: {tokens:.1f} tokens @ ${trader_price} "
                f"(value: ${capped_value:.2f}, trader: {trader_size:.1f} @ ${trader_price})"
            )
            
            return max(1, int(tokens))
        
        except Exception as e:
            logger.error(f"Error calculating position size: {e}")
            return 0
    
    async def check_liquidity(
        self,
        token_id: str,
        max_spread: float = 0.05
    ) -> bool:
        """Check if market is liquid enough to trade"""
        
        try:
            orderbook = await self.clob_client.get_orderbook(token_id)
            
            if not orderbook:
                logger.warning(f"No orderbook data for {token_id}")
                return False
            
            bids = orderbook.get("bids", [])
            asks = orderbook.get("asks", [])
            
            if not bids or not asks:
                logger.warning(f"No bids/asks for {token_id}")
                return False
            
            best_bid = float(bids[0].get("price", 0))
            best_ask = float(asks[0].get("price", 1))
            
            spread = (best_ask - best_bid) / ((best_bid + best_ask) / 2)
            
            logger.info(f"Spread for {token_id}: {spread:.2%}")
            
            return spread <= max_spread
        
        except Exception as e:
            logger.error(f"Error checking liquidity: {e}")
            return False
    
    async def place_order(
        self,
        token_id: str,
        price: float,
        size: float,
        side: str = "BUY",
        order_type: str = "GTC"
    ) -> Optional[Dict[str, Any]]:
        """Place order with slippage protection"""
        
        try:
            # Get current market price
            book = await self.clob_client.get_orderbook(token_id)
            if not book:
                logger.warning(f"Can't get orderbook for {token_id}, skipping")
                return None
            
            mid_price = price  # Use trader's entry as reference
            max_slippage = 0.01  # 1% max slippage
            
            if side.upper() == "BUY":
                max_price = mid_price * (1 + max_slippage)
            else:
                max_price = mid_price * (1 - max_slippage)
            
            # Use safer price
            order_price = min(price, max_price) if side.upper() == "BUY" else max(price, max_price)
            
            logger.info(f"Placing {side} order: {size}x @ ${order_price:.2f}")
            
            response = await self.clob_client.place_order(
                token_id=token_id,
                price=order_price,
                size=size,
                side=side,
                order_type=order_type
            )
            
            if response:
                return {
                    "order_id": response.get("orderID"),
                    "token_id": token_id,
                    "price": order_price,
                    "size": size,
                    "side": side,
                    "status": response.get("status"),
                    "pnl": 0  # Will be updated when position closes
                }
            
            return None
        
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return None
    
    async def close_position(
        self,
        token_id: str,
        size: float,
        side: str = "SELL"
    ) -> Optional[Dict[str, Any]]:
        """Close a position (sell if we bought)"""
        
        opposite_side = "SELL" if side.upper() == "BUY" else "BUY"
        
        return await self.place_order(
            token_id=token_id,
            price=0.50,  # Market order (will execute at best price)
            size=size,
            side=opposite_side,
            order_type="IOC"  # Immediate or cancel
        )
    
    async def get_open_orders(self) -> list:
        """Get all open orders"""
        try:
            return await self.clob_client.get_user_orders()
        except Exception as e:
            logger.error(f"Error fetching orders: {e}")
            return []
