"""
Local storage: SQLite for trade logging and P&L tracking
"""

import logging
import sqlite3
from datetime import datetime, timedelta
from typing import List, Dict, Any
import json

logger = logging.getLogger(__name__)


class Storage:
    """SQLite storage for trades and P&L"""
    
    def __init__(self, db_path: str = "trades.db"):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """Initialize database schema"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Trades table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS trades (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        order_id TEXT UNIQUE,
                        trader_address TEXT,
                        market_id TEXT,
                        market_title TEXT,
                        side TEXT,
                        price REAL,
                        size REAL,
                        value REAL,
                        status TEXT,
                        pnl REAL DEFAULT 0,
                        realized_pnl REAL DEFAULT 0,
                        closed_at TEXT
                    )
                """)
                
                # Portfolio snapshot table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS portfolio (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        equity REAL,
                        cash REAL,
                        open_pnl REAL,
                        realized_pnl REAL,
                        total_pnl REAL,
                        num_positions INTEGER
                    )
                """)
                
                conn.commit()
                logger.info(f"Database initialized: {self.db_path}")
        
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            raise
    
    def log_trade(self, trade: Dict[str, Any]):
        """Log a trade execution"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO trades (
                        timestamp, order_id, market_id, market_title,
                        side, price, size, value, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    datetime.now().isoformat(),
                    trade.get("order_id", "unknown"),
                    trade.get("token_id", ""),
                    trade.get("market", ""),
                    trade.get("side", "BUY"),
                    trade.get("price", 0),
                    trade.get("size", 0),
                    trade.get("size", 0) * trade.get("price", 0),
                    trade.get("status", "PENDING")
                ))
                conn.commit()
                logger.info(f"Trade logged: {trade.get('order_id')}")
        
        except Exception as e:
            logger.error(f"Error logging trade: {e}")
    
    def update_trade_pnl(self, order_id: str, pnl: float, realized: bool = False):
        """Update P&L for a trade"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                if realized:
                    cursor.execute("""
                        UPDATE trades
                        SET realized_pnl = ?, status = 'CLOSED', closed_at = ?
                        WHERE order_id = ?
                    """, (pnl, datetime.now().isoformat(), order_id))
                else:
                    cursor.execute("""
                        UPDATE trades
                        SET pnl = ?
                        WHERE order_id = ?
                    """, (pnl, order_id))
                
                conn.commit()
        
        except Exception as e:
            logger.error(f"Error updating trade P&L: {e}")
    
    def log_portfolio(
        self,
        equity: float,
        cash: float,
        open_pnl: float,
        realized_pnl: float,
        num_positions: int
    ):
        """Log portfolio snapshot"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO portfolio (
                        timestamp, equity, cash, open_pnl, realized_pnl, total_pnl, num_positions
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    datetime.now().isoformat(),
                    equity,
                    cash,
                    open_pnl,
                    realized_pnl,
                    open_pnl + realized_pnl,
                    num_positions
                ))
                conn.commit()
        
        except Exception as e:
            logger.error(f"Error logging portfolio: {e}")
    
    def get_recent_trades(self, hours: int = 1) -> List[Dict[str, Any]]:
        """Get recent trades"""
        try:
            cutoff = datetime.now() - timedelta(hours=hours)
            
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT * FROM trades
                    WHERE timestamp > ?
                    ORDER BY timestamp DESC
                """, (cutoff.isoformat(),))
                
                return [dict(row) for row in cursor.fetchall()]
        
        except Exception as e:
            logger.error(f"Error fetching trades: {e}")
            return []
    
    def get_portfolio_history(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Get portfolio snapshots over time"""
        try:
            cutoff = datetime.now() - timedelta(hours=hours)
            
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT * FROM portfolio
                    WHERE timestamp > ?
                    ORDER BY timestamp ASC
                """, (cutoff.isoformat(),))
                
                return [dict(row) for row in cursor.fetchall()]
        
        except Exception as e:
            logger.error(f"Error fetching portfolio history: {e}")
            return []
    
    def get_stats(self) -> Dict[str, Any]:
        """Get overall stats"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Total trades
                cursor.execute("SELECT COUNT(*) as count FROM trades")
                total_trades = cursor.fetchone()[0]
                
                # Winning trades
                cursor.execute("""
                    SELECT COUNT(*) as count FROM trades
                    WHERE realized_pnl > 0
                """)
                winning_trades = cursor.fetchone()[0]
                
                # Total P&L
                cursor.execute("""
                    SELECT SUM(realized_pnl) as total FROM trades
                """)
                total_pnl = cursor.fetchone()[0] or 0
                
                return {
                    "total_trades": total_trades,
                    "winning_trades": winning_trades,
                    "win_rate": (winning_trades / total_trades * 100) if total_trades > 0 else 0,
                    "total_pnl": total_pnl
                }
        
        except Exception as e:
            logger.error(f"Error calculating stats: {e}")
            return {}
