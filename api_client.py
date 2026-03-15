"""
API client wrappers for Polymarket CLOB and Data APIs
"""

import logging
from typing import Optional, Dict, List, Any
import aiohttp
import requests
from py_clob_client.client import ClobClient
from ethers import Wallet

logger = logging.getLogger(__name__)


class PolymarketDataClient:
    """Wrapper for Polymarket Data API (public, no auth)"""
    
    def __init__(self, host: str = "https://data-api.polymarket.com"):
        self.host = host
        self.session = None
    
    async def get_leaderboard(
        self,
        category: str = "OVERALL",
        time_period: str = "MONTH",
        order_by: str = "PNL",
        limit: int = 10,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Fetch trader leaderboard
        
        Parameters:
            category: OVERALL|POLITICS|SPORTS|CRYPTO|CULTURE|WEATHER|ECONOMICS|TECH|FINANCE
            time_period: DAY|WEEK|MONTH|ALL
            order_by: PNL|VOL
            limit: 1-50
            offset: pagination
        """
        try:
            url = f"{self.host}/v1/leaderboard"
            params = {
                "category": category,
                "timePeriod": time_period,
                "orderBy": order_by,
                "limit": limit,
                "offset": offset
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=10) as resp:
                    if resp.status != 200:
                        logger.error(f"Leaderboard API error: {resp.status}")
                        return []
                    
                    data = await resp.json()
                    logger.info(f"Fetched {len(data)} leaderboard entries")
                    return data
        
        except Exception as e:
            logger.error(f"Error fetching leaderboard: {e}")
            return []
    
    async def get_positions(
        self,
        user: str,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Fetch current positions for a user
        
        Parameters:
            user: wallet address (0x...)
            limit: 1-500
            offset: pagination
        """
        try:
            url = f"{self.host}/positions"
            params = {
                "user": user,
                "limit": limit,
                "offset": offset,
                "sortBy": "TOKENS",
                "sortDirection": "DESC"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=10) as resp:
                    if resp.status != 200:
                        logger.error(f"Positions API error: {resp.status}")
                        return []
                    
                    data = await resp.json()
                    logger.info(f"Fetched {len(data)} positions for {user}")
                    return data
        
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return []
    
    async def get_trades(
        self,
        user: str,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Fetch trade history for a user"""
        try:
            url = f"{self.host}/trades"
            params = {
                "user": user,
                "limit": limit,
                "offset": offset
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=10) as resp:
                    if resp.status != 200:
                        return []
                    return await resp.json()
        
        except Exception as e:
            logger.error(f"Error fetching trades: {e}")
            return []


class PolymarketClient:
    """Wrapper for Polymarket CLOB API (authenticated trading)"""
    
    def __init__(
        self,
        private_key: str,
        wallet_address: str,
        chain_id: int = 137,
        host: str = "https://clob.polymarket.com",
        dry_run: bool = True
    ):
        self.private_key = private_key
        self.wallet_address = wallet_address
        self.chain_id = chain_id
        self.host = host
        self.dry_run = dry_run
        self.client = None
        self.api_creds = None
    
    async def initialize(self):
        """Initialize CLOB client (derive API credentials)"""
        try:
            signer = Wallet(self.private_key)
            
            # Create temporary client to derive API creds
            temp_client = ClobClient(
                host=self.host,
                key=self.private_key,
                chain_id=self.chain_id
            )
            
            self.api_creds = temp_client.create_or_derive_api_creds()
            logger.info(f"API credentials derived for {self.wallet_address}")
            
            # Create authenticated client
            self.client = ClobClient(
                host=self.host,
                key=self.private_key,
                chain_id=self.chain_id,
                creds=self.api_creds
            )
        
        except Exception as e:
            logger.error(f"Failed to initialize CLOB client: {e}")
            raise
    
    async def get_market(self, condition_id: str) -> Optional[Dict[str, Any]]:
        """Get market details (for tick size, neg risk, etc.)"""
        try:
            if not self.client:
                await self.initialize()
            
            market = self.client.get_market(condition_id)
            return market
        
        except Exception as e:
            logger.error(f"Error fetching market: {e}")
            return None
    
    async def get_orderbook(self, token_id: str) -> Optional[Dict[str, Any]]:
        """Get orderbook for a token"""
        try:
            if not self.client:
                await self.initialize()
            
            book = self.client.get_order_book(token_id)
            return book
        
        except Exception as e:
            logger.error(f"Error fetching orderbook: {e}")
            return None
    
    async def place_order(
        self,
        token_id: str,
        price: float,
        size: float,
        side: str = "BUY",
        order_type: str = "GTC"
    ) -> Optional[Dict[str, Any]]:
        """
        Place a limit order
        
        Parameters:
            token_id: outcome token ID
            price: limit price (0-1)
            size: number of tokens to trade
            side: BUY|SELL
            order_type: GTC (Good-till-cancelled) or IOC (Immediate-or-cancel)
        """
        if self.dry_run:
            logger.info(f"DRY RUN: Would place {side} order: {size}x @ ${price} (token: {token_id})")
            return {
                "orderID": "DRY_RUN_12345",
                "status": "DRY_RUN",
                "tokenID": token_id,
                "price": price,
                "size": size,
                "side": side
            }
        
        try:
            if not self.client:
                await self.initialize()
            
            from py_clob_client.clob_types import OrderArgs, OrderType
            from py_clob_client.order_builder.constants import BUY, SELL
            
            side_const = BUY if side.upper() == "BUY" else SELL
            order_type_const = OrderType.GTC if order_type == "GTC" else OrderType.IOC
            
            response = self.client.create_and_post_order(
                OrderArgs(
                    token_id=token_id,
                    price=price,
                    size=size,
                    side=side_const,
                    order_type=order_type_const
                ),
                options={
                    "tick_size": "0.01",
                    "neg_risk": False
                }
            )
            
            logger.info(f"Order placed: {response}")
            return response
        
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return None
    
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order"""
        if self.dry_run:
            logger.info(f"DRY RUN: Would cancel order {order_id}")
            return True
        
        try:
            if not self.client:
                await self.initialize()
            
            self.client.cancel_order(order_id)
            logger.info(f"Order cancelled: {order_id}")
            return True
        
        except Exception as e:
            logger.error(f"Error cancelling order: {e}")
            return False
    
    async def get_user_orders(self) -> List[Dict[str, Any]]:
        """Get all open orders for authenticated user"""
        try:
            if not self.client:
                await self.initialize()
            
            orders = self.client.get_user_orders()
            return orders or []
        
        except Exception as e:
            logger.error(f"Error fetching user orders: {e}")
            return []
