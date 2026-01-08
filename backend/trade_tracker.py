"""
Trade Accountability System - Tracks and persists signal performance
Uses SQLite for trade history storage with non-blocking writes on closure only
"""
import sqlite3
import logging
import time
import json
import uuid
from typing import Optional, Dict, List, Any
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class ActiveTrade:
    """In-memory representation of an active trade"""
    id: str
    symbol: str
    direction: str  # LONG or SHORT
    entry_time: float
    entry_price: float
    tp1: float
    sl: float
    max_favorable: float = 0.0
    max_adverse: float = 0.0
    price_snapshots: List[Dict] = field(default_factory=list)
    last_snapshot_time: float = 0.0
    outcome: Optional[str] = None  # WIN, LOSS, EXPIRED
    exit_price: Optional[float] = None
    exit_time: Optional[float] = None


class TradeTracker:
    """
    Tracks active trades in memory and persists completed trades to SQLite.
    Non-blocking: Only writes to DB when a trade closes.
    P&L calculated based on $100,000 capital with 10x leverage.
    """
    
    # Capital and leverage for P&L calculation
    CAPITAL = 100000.0      # $100K base capital
    LEVERAGE = 10           # 10x leverage
    POSITION_SIZE = CAPITAL * LEVERAGE  # $1M effective position
    
    def __init__(self, symbol: str, db_path: str = "/app/data/trades.db"):
        self.symbol = symbol
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Active trade (only one at a time per symbol)
        self.active_trade: Optional[ActiveTrade] = None
        
        # Initialize database
        self._init_db()
        
        logger.info(f"{symbol}: TradeTracker initialized with DB at {db_path}")
    
    def _init_db(self):
        """Initialize SQLite database and create tables if needed"""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    entry_time REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_time REAL,
                    exit_price REAL,
                    tp1 REAL NOT NULL,
                    sl REAL NOT NULL,
                    outcome TEXT,
                    pnl_absolute REAL,
                    pnl_percent REAL,
                    roi_percent REAL,
                    max_favorable REAL,
                    max_adverse REAL,
                    price_snapshots_json TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Add roi_percent column if it doesn't exist (migration for existing DBs)
            try:
                cursor.execute("ALTER TABLE trades ADD COLUMN roi_percent REAL")
            except sqlite3.OperationalError:
                pass  # Column already exists
            
            # Create index for faster queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_symbol_time 
                ON trades(symbol, entry_time DESC)
            """)
            
            conn.commit()
            conn.close()
            logger.debug(f"{self.symbol}: Database initialized successfully")
            
        except Exception as e:
            logger.error(f"{self.symbol}: Error initializing database: {e}")
    
    def start_trade(self, signal_data: Dict) -> Optional[str]:
        """
        Start tracking a new trade when a signal becomes ACTIVE.
        
        Args:
            signal_data: Dict containing direction, entry_price, tp1, sl
            
        Returns:
            Trade ID if started, None if trade already active
        """
        try:
            # Don't start a new trade if one is already active
            if self.active_trade is not None:
                logger.warning(f"{self.symbol}: Cannot start trade - one already active")
                return None
            
            trade_id = str(uuid.uuid4())[:8]
            current_time = time.time()
            
            self.active_trade = ActiveTrade(
                id=trade_id,
                symbol=self.symbol,
                direction=signal_data.get('direction', 'LONG'),
                entry_time=current_time,
                entry_price=signal_data.get('entry_price', 0),
                tp1=signal_data.get('tp1', 0),
                sl=signal_data.get('sl', 0),
                max_favorable=0.0,
                max_adverse=0.0,
                price_snapshots=[],
                last_snapshot_time=current_time
            )
            
            logger.info(f"{self.symbol}: Started tracking trade {trade_id} - "
                       f"{self.active_trade.direction} @ {self.active_trade.entry_price:.2f}")
            
            return trade_id
            
        except Exception as e:
            logger.error(f"{self.symbol}: Error starting trade: {e}")
            return None
    
    def update(self, current_price: float) -> Optional[Dict]:
        """
        Update active trade with current price.
        - Updates MFE/MAE (based on $100k capital @ 10x leverage)
        - Captures snapshots at 10s intervals
        - Checks TP/SL hits
        - Auto-closes after 60s
        
        Args:
            current_price: Current market price
            
        Returns:
            Trade result dict if closed, None otherwise
        """
        if self.active_trade is None or current_price is None:
            return None
        
        try:
            trade = self.active_trade
            current_time = time.time()
            elapsed = current_time - trade.entry_time
            
            # Calculate price change (absolute)
            if trade.direction == 'LONG':
                price_change = current_price - trade.entry_price
            else:  # SHORT
                price_change = trade.entry_price - current_price
            
            # Calculate P&L based on $100k capital @ 10x leverage ($1M position)
            # P&L = (price_change / entry_price) * POSITION_SIZE
            pnl_dollar = (price_change / trade.entry_price) * self.POSITION_SIZE
            
            # Update max favorable (MFE) and max adverse (MAE) in dollar terms
            if price_change > 0:
                mfe_dollar = (price_change / trade.entry_price) * self.POSITION_SIZE
                trade.max_favorable = max(trade.max_favorable, mfe_dollar)
            else:
                mae_dollar = (abs(price_change) / trade.entry_price) * self.POSITION_SIZE
                trade.max_adverse = max(trade.max_adverse, mae_dollar)
            
            # Capture price snapshots at 10s intervals
            time_since_last_snapshot = current_time - trade.last_snapshot_time
            if time_since_last_snapshot >= 10.0 and len(trade.price_snapshots) < 6:
                snapshot = {
                    'time': round(elapsed, 1),
                    'price': current_price,
                    'pnl': round(pnl_dollar, 2)  # P&L in dollars based on $100k capital
                }
                trade.price_snapshots.append(snapshot)
                trade.last_snapshot_time = current_time
                logger.debug(f"{self.symbol}: Snapshot @ {elapsed:.0f}s: ${current_price:.2f}, PnL: ${pnl_dollar:.2f}")
            
            # Check TP1 hit
            tp_hit = False
            if trade.direction == 'LONG':
                tp_hit = current_price >= trade.tp1
            else:  # SHORT
                tp_hit = current_price <= trade.tp1
            
            if tp_hit:
                return self._close_trade('WIN', current_price, current_time)
            
            # Check SL hit
            sl_hit = False
            if trade.direction == 'LONG':
                sl_hit = current_price <= trade.sl
            else:  # SHORT
                sl_hit = current_price >= trade.sl
            
            if sl_hit:
                return self._close_trade('LOSS', current_price, current_time)
            
            # Auto-close after 60 seconds
            if elapsed >= 60.0:
                # Determine outcome based on final P&L
                if pnl_dollar > 0:
                    outcome = 'WIN'
                elif pnl_dollar < 0:
                    outcome = 'LOSS'
                else:
                    outcome = 'EXPIRED'
                return self._close_trade(outcome, current_price, current_time)
            
            return None
            
        except Exception as e:
            logger.error(f"{self.symbol}: Error updating trade: {e}")
            return None
    
    def _close_trade(self, outcome: str, exit_price: float, exit_time: float) -> Dict:
        """
        Close the active trade and persist to SQLite.
        P&L calculated based on $100,000 capital @ 10x leverage.
        
        Args:
            outcome: WIN, LOSS, or EXPIRED
            exit_price: Price at trade closure
            exit_time: Timestamp of closure
            
        Returns:
            Dict with trade results
        """
        try:
            trade = self.active_trade
            
            # Calculate price change
            if trade.direction == 'LONG':
                price_change = exit_price - trade.entry_price
            else:  # SHORT
                price_change = trade.entry_price - exit_price
            
            # Calculate P&L based on $100k capital @ 10x leverage ($1M position)
            pnl_percent = (price_change / trade.entry_price) * 100  # Raw price change %
            pnl_dollar = (price_change / trade.entry_price) * self.POSITION_SIZE
            
            # ROI% = P&L / Capital (shows return on actual capital deployed)
            roi_percent = (pnl_dollar / self.CAPITAL) * 100
            
            # Build result dict
            result = {
                'id': trade.id,
                'symbol': trade.symbol,
                'direction': trade.direction,
                'entry_time': trade.entry_time,
                'entry_price': trade.entry_price,
                'exit_time': exit_time,
                'exit_price': exit_price,
                'tp1': trade.tp1,
                'sl': trade.sl,
                'outcome': outcome,
                'pnl_absolute': round(pnl_dollar, 2),      # Dollar P&L (with leverage)
                'pnl_percent': round(pnl_percent, 4),      # Raw price change %
                'roi_percent': round(roi_percent, 4),      # ROI on capital (leveraged)
                'max_favorable': round(trade.max_favorable, 2),  # Already in dollars
                'max_adverse': round(trade.max_adverse, 2),      # Already in dollars
                'duration': round(exit_time - trade.entry_time, 1),
                'price_snapshots': trade.price_snapshots
            }
            
            # Persist to database (non-blocking - only on closure)
            self._persist_trade(result)
            
            logger.info(f"{self.symbol}: Trade {trade.id} CLOSED - {outcome} | "
                       f"PnL: ${pnl_dollar:.2f} (ROI: {roi_percent:.2f}%) | "
                       f"MFE: ${trade.max_favorable:.2f} | MAE: ${trade.max_adverse:.2f}")
            
            # Clear active trade
            self.active_trade = None
            
            return result
            
        except Exception as e:
            logger.error(f"{self.symbol}: Error closing trade: {e}")
            self.active_trade = None
            return {}
    
    def _persist_trade(self, trade_data: Dict):
        """Write completed trade to SQLite database"""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO trades (
                    id, symbol, direction, entry_time, entry_price,
                    exit_time, exit_price, tp1, sl, outcome,
                    pnl_absolute, pnl_percent, max_favorable, max_adverse,
                    price_snapshots_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade_data['id'],
                trade_data['symbol'],
                trade_data['direction'],
                trade_data['entry_time'],
                trade_data['entry_price'],
                trade_data['exit_time'],
                trade_data['exit_price'],
                trade_data['tp1'],
                trade_data['sl'],
                trade_data['outcome'],
                trade_data['pnl_absolute'],
                trade_data['pnl_percent'],
                trade_data['max_favorable'],
                trade_data['max_adverse'],
                json.dumps(trade_data['price_snapshots'])
            ))
            
            conn.commit()
            conn.close()
            logger.debug(f"{self.symbol}: Trade {trade_data['id']} persisted to database")
            
        except Exception as e:
            logger.error(f"{self.symbol}: Error persisting trade: {e}")
    
    def get_recent_trades(self, limit: int = 50) -> List[Dict]:
        """
        Retrieve recent trades from SQLite.
        
        Args:
            limit: Maximum number of trades to return
            
        Returns:
            List of trade dictionaries
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT 
                    id, symbol, direction, entry_time, entry_price,
                    exit_time, exit_price, tp1, sl, outcome,
                    pnl_absolute, pnl_percent, max_favorable, max_adverse,
                    price_snapshots_json, created_at
                FROM trades
                WHERE symbol = ?
                ORDER BY entry_time DESC
                LIMIT ?
            """, (self.symbol, limit))
            
            rows = cursor.fetchall()
            conn.close()
            
            trades = []
            for row in rows:
                trade = dict(row)
                # Parse JSON snapshots
                if trade.get('price_snapshots_json'):
                    trade['price_snapshots'] = json.loads(trade['price_snapshots_json'])
                else:
                    trade['price_snapshots'] = []
                del trade['price_snapshots_json']
                trades.append(trade)
            
            return trades
            
        except Exception as e:
            logger.error(f"{self.symbol}: Error retrieving trades: {e}")
            return []
    
    def get_stats(self) -> Dict:
        """Get aggregate statistics for this symbol"""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN outcome = 'LOSS' THEN 1 ELSE 0 END) as losses,
                    SUM(pnl_absolute) as total_pnl,
                    AVG(pnl_absolute) as avg_pnl,
                    AVG(max_favorable) as avg_mfe,
                    AVG(max_adverse) as avg_mae
                FROM trades
                WHERE symbol = ?
            """, (self.symbol,))
            
            row = cursor.fetchone()
            conn.close()
            
            if row and row[0] > 0:
                total = row[0]
                wins = row[1] or 0
                return {
                    'total_trades': total,
                    'wins': wins,
                    'losses': row[2] or 0,
                    'win_rate': round((wins / total) * 100, 1) if total > 0 else 0,
                    'total_pnl': round(row[3] or 0, 2),
                    'avg_pnl': round(row[4] or 0, 2),
                    'avg_mfe': round(row[5] or 0, 2),
                    'avg_mae': round(row[6] or 0, 2)
                }
            
            return {
                'total_trades': 0,
                'wins': 0,
                'losses': 0,
                'win_rate': 0,
                'total_pnl': 0,
                'avg_pnl': 0,
                'avg_mfe': 0,
                'avg_mae': 0
            }
            
        except Exception as e:
            logger.error(f"{self.symbol}: Error getting stats: {e}")
            return {}
    
    def has_active_trade(self) -> bool:
        """Check if there's an active trade"""
        return self.active_trade is not None
    
    def get_active_trade_info(self) -> Optional[Dict]:
        """Get info about the currently active trade"""
        if self.active_trade is None:
            return None
        
        trade = self.active_trade
        elapsed = time.time() - trade.entry_time
        
        return {
            'id': trade.id,
            'symbol': trade.symbol,
            'direction': trade.direction,
            'entry_price': trade.entry_price,
            'tp1': trade.tp1,
            'sl': trade.sl,
            'elapsed': round(elapsed, 1),
            'max_favorable': round(trade.max_favorable, 2),
            'max_adverse': round(trade.max_adverse, 2),
            'snapshots_count': len(trade.price_snapshots)
        }


def get_all_recent_trades(db_path: str = "/app/data/trades.db", limit: int = 50) -> List[Dict]:
    """
    Static function to get recent trades across ALL symbols.
    Used by the API endpoint.
    """
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                id, symbol, direction, entry_time, entry_price,
                exit_time, exit_price, tp1, sl, outcome,
                pnl_absolute, pnl_percent, max_favorable, max_adverse,
                price_snapshots_json, created_at
            FROM trades
            ORDER BY entry_time DESC
            LIMIT ?
        """, (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        
        trades = []
        for row in rows:
            trade = dict(row)
            if trade.get('price_snapshots_json'):
                trade['price_snapshots'] = json.loads(trade['price_snapshots_json'])
            else:
                trade['price_snapshots'] = []
            del trade['price_snapshots_json']
            trades.append(trade)
        
        return trades
        
    except Exception as e:
        logger.error(f"Error retrieving all trades: {e}")
        return []


def get_aggregate_stats(db_path: str = "/app/data/trades.db") -> Dict:
    """
    Static function to get aggregate statistics across ALL symbols.
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                COUNT(*) as total_trades,
                SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN outcome = 'LOSS' THEN 1 ELSE 0 END) as losses,
                SUM(pnl_absolute) as total_pnl,
                AVG(pnl_absolute) as avg_pnl
            FROM trades
        """)
        
        row = cursor.fetchone()
        conn.close()
        
        if row and row[0] > 0:
            total = row[0]
            wins = row[1] or 0
            return {
                'total_trades': total,
                'wins': wins,
                'losses': row[2] or 0,
                'win_rate': round((wins / total) * 100, 1) if total > 0 else 0,
                'total_pnl': round(row[3] or 0, 2),
                'avg_pnl': round(row[4] or 0, 2)
            }
        
        return {
            'total_trades': 0,
            'wins': 0,
            'losses': 0,
            'win_rate': 0,
            'total_pnl': 0,
            'avg_pnl': 0
        }
        
    except Exception as e:
        logger.error(f"Error getting aggregate stats: {e}")
        return {}


def migrate_trades_to_capital_based(db_path: str = "/app/data/trades.db", capital: float = 100000.0) -> Dict:
    """
    Migrate existing trades to use capital-based P&L calculations.
    Recalculates pnl_absolute and max_favorable/max_adverse based on $100k capital.
    
    Returns:
        Dict with migration results
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get all trades
        cursor.execute("""
            SELECT id, entry_price, exit_price, direction, pnl_percent, max_favorable, max_adverse
            FROM trades
        """)
        
        rows = cursor.fetchall()
        updated_count = 0
        
        for row in rows:
            trade_id, entry_price, exit_price, direction, pnl_percent, old_mfe, old_mae = row
            
            if entry_price is None or entry_price == 0:
                continue
            
            # Recalculate P&L based on capital
            # pnl_absolute = (pnl_percent / 100) * capital
            new_pnl = (pnl_percent / 100) * capital if pnl_percent else 0
            
            # Recalculate MFE/MAE based on capital
            # Old values were absolute price differences, convert to dollar P&L
            # If old_mfe was price difference, new_mfe = (old_mfe / entry_price) * capital
            if old_mfe and entry_price:
                # Check if old value looks like a price difference (small relative to entry)
                if abs(old_mfe) < entry_price * 0.1:  # Less than 10% of entry = likely price diff
                    new_mfe = (old_mfe / entry_price) * capital
                else:
                    new_mfe = old_mfe  # Already converted or very large move
            else:
                new_mfe = 0
                
            if old_mae and entry_price:
                if abs(old_mae) < entry_price * 0.1:
                    new_mae = (old_mae / entry_price) * capital
                else:
                    new_mae = old_mae
            else:
                new_mae = 0
            
            # Update the trade
            cursor.execute("""
                UPDATE trades 
                SET pnl_absolute = ?, max_favorable = ?, max_adverse = ?
                WHERE id = ?
            """, (round(new_pnl, 2), round(new_mfe, 2), round(new_mae, 2), trade_id))
            
            updated_count += 1
        
        conn.commit()
        conn.close()
        
        logger.info(f"Migrated {updated_count} trades to capital-based P&L (${capital:,.0f})")
        
        return {
            'status': 'success',
            'trades_updated': updated_count,
            'capital': capital
        }
        
    except Exception as e:
        logger.error(f"Error migrating trades: {e}")
        return {'status': 'error', 'message': str(e)}
