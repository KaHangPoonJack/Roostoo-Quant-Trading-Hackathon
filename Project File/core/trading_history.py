"""
trading_history.py
==================
Database module for tracking trading history and live metrics
"""

import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional

# Use the project root for database location
DB_PATH = Path(__file__).parent.parent / "trading_data.db"


class TradingHistory:
    """SQLite database for trading history and metrics"""
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(DB_PATH)
        self.lock = Lock()
        self._initialize_db()
    
    def _initialize_db(self):
        """Create tables if they don't exist"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Trades table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    entry_time TIMESTAMP NOT NULL,
                    entry_price REAL NOT NULL,
                    side TEXT NOT NULL,
                    predicted_class INTEGER,
                    predicted_probs TEXT,
                    exit_time TIMESTAMP,
                    exit_price REAL,
                    pnl_pct REAL,
                    reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Live metrics table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS live_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP NOT NULL,
                    symbol TEXT NOT NULL,
                    current_price REAL,
                    last_predicted_class INTEGER,
                    last_predicted_probs TEXT,
                    open_trade BOOLEAN,
                    open_trade_pnl_pct REAL,
                    total_pnl_pct REAL,
                    trades_count INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # ML Predictions table - NEW
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ml_predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP NOT NULL,
                    symbol TEXT NOT NULL,
                    predicted_class INTEGER,
                    confidence REAL,
                    probabilities TEXT,
                    breakout_prob REAL,
                    recommendation TEXT,
                    tp_target REAL,
                    sl_limit REAL,
                    position_size_pct REAL,
                    price REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # PnL Updates table - NEW for tracking P&L over time
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pnl_updates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP NOT NULL,
                    symbol TEXT NOT NULL,
                    entry_price REAL,
                    current_price REAL,
                    pnl_pct REAL,
                    side TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create indexes for faster queries
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ml_predictions_symbol ON ml_predictions(symbol)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ml_predictions_timestamp ON ml_predictions(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_pnl_updates_symbol ON pnl_updates(symbol)")

            conn.commit()

    def record_ml_prediction(self, symbol: str, prediction: dict):
        """Record ML prediction data"""
        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                probs_json = json.dumps(prediction.get('probabilities', [])) if prediction.get('probabilities') else None
                
                cursor.execute("""
                    INSERT INTO ml_predictions
                    (timestamp, symbol, predicted_class, confidence, probabilities, 
                     breakout_prob, recommendation, tp_target, sl_limit, 
                     position_size_pct, price)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    datetime.now(timezone.utc),
                    symbol,
                    prediction.get('predicted_class'),
                    prediction.get('confidence'),
                    probs_json,
                    prediction.get('breakout_probability'),
                    prediction.get('recommendation'),
                    prediction.get('tp_target'),
                    prediction.get('sl_limit'),
                    prediction.get('position_size_pct'),
                    prediction.get('price')
                ))
                
                conn.commit()
                return cursor.lastrowid

    def record_pnl_update(self, symbol: str, entry_price: float, current_price: float, 
                         pnl_pct: float, side: str):
        """Record P&L update for open trades"""
        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT INTO pnl_updates
                    (timestamp, symbol, entry_price, current_price, pnl_pct, side)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    datetime.now(timezone.utc),
                    symbol,
                    entry_price,
                    current_price,
                    pnl_pct,
                    side
                ))
                
                conn.commit()
                return cursor.lastrowid

    def get_recent_ml_predictions(self, symbol: str = None, limit: int = 50):
        """Get recent ML predictions"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            if symbol:
                cursor.execute("""
                    SELECT * FROM ml_predictions
                    WHERE symbol = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (symbol, limit))
            else:
                cursor.execute("""
                    SELECT * FROM ml_predictions
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (limit,))
            
            rows = cursor.fetchall()
            results = []
            for row in rows:
                result = dict(row)
                if result.get('probabilities'):
                    try:
                        result['probabilities'] = json.loads(result['probabilities'])
                    except:
                        pass
                results.append(result)
            
            return results

    def get_daily_ml_summary(self, date: datetime):
        """Get ML prediction summary for a specific date"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            start_date = date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = date.replace(hour=23, minute=59, second=59, microsecond=999999)
            
            cursor.execute("""
                SELECT symbol, 
                       COUNT(*) as total_predictions,
                       AVG(predicted_class) as avg_class,
                       AVG(confidence) as avg_confidence,
                       AVG(breakout_prob) as avg_breakout_prob
                FROM ml_predictions
                WHERE timestamp BETWEEN ? AND ?
                GROUP BY symbol
            """, (start_date, end_date))
            
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_trades_by_date(self, date: datetime):
        """Get all trades for a specific date (by entry_time or exit_time)"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            start_date = date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = date.replace(hour=23, minute=59, second=59, microsecond=999999)

            # Get trades that were entered OR exited on this date
            cursor.execute("""
                SELECT * FROM trades
                WHERE (entry_time BETWEEN ? AND ?)
                   OR (exit_time BETWEEN ? AND ?)
                   OR (exit_time IS NULL AND entry_time BETWEEN ? AND ?)
                ORDER BY entry_time DESC
            """, (start_date, end_date, start_date, end_date, start_date, end_date))

            rows = cursor.fetchall()
            results = []
            for row in rows:
                result = dict(row)
                if result.get('predicted_probs'):
                    try:
                        result['predicted_probs'] = json.loads(result['predicted_probs'])
                    except:
                        pass
                results.append(result)

            return results

    def get_open_trades_with_pnl(self):
        """Get all open trades (no exit_time)"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM trades
                WHERE exit_time IS NULL
                ORDER BY entry_time DESC
            """)

            rows = cursor.fetchall()
            results = []
            for row in rows:
                result = dict(row)
                if result.get('predicted_probs'):
                    try:
                        result['predicted_probs'] = json.loads(result['predicted_probs'])
                    except:
                        pass
                results.append(result)

            return results

    def record_trade_entry(self, symbol: str, entry_price: float, side: str,
                          predicted_class: int = None, predicted_probs: Dict = None):
        """Record entry of a new trade"""
        print(f"📝 [DB] Recording trade entry for {symbol} @ ${entry_price}")
        print(f"📝 [DB] Database path: {self.db_path}")
        
        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Check if trades table exists
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='trades'")
                if not cursor.fetchone():
                    print(f"⚠️  [DB] Trades table doesn't exist! Creating it...")
                    self._initialize_db()  # Re-initialize to create missing tables
                
                probs_json = json.dumps(predicted_probs) if predicted_probs else None

                cursor.execute("""
                    INSERT INTO trades
                    (symbol, entry_time, entry_price, side, predicted_class, predicted_probs)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    symbol,
                    datetime.now(timezone.utc),
                    entry_price,
                    side,
                    predicted_class,
                    probs_json
                ))

                conn.commit()
                trade_id = cursor.lastrowid
                print(f"✅ [DB] Trade entry recorded with ID: {trade_id}")
                return trade_id
    
    def record_trade_exit(self, trade_id: int, exit_price: float, pnl_pct: float, reason: str = None):
        """Record exit of an open trade"""
        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    UPDATE trades
                    SET exit_time = ?, exit_price = ?, pnl_pct = ?, reason = ?
                    WHERE id = ?
                """, (
                    datetime.now(timezone.utc),
                    exit_price,
                    pnl_pct,
                    reason,
                    trade_id
                ))
                
                conn.commit()
    
    def record_metrics(self, symbol: str, current_price: float, 
                      last_predicted_class: int = None,
                      last_predicted_probs: Dict = None,
                      open_trade: bool = False,
                      open_trade_pnl_pct: float = 0.0,
                      total_pnl_pct: float = 0.0,
                      trades_count: int = 0):
        """Record live trading metrics"""
        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                probs_json = json.dumps(last_predicted_probs) if last_predicted_probs else None
                
                cursor.execute("""
                    INSERT INTO live_metrics
                    (timestamp, symbol, current_price, last_predicted_class, last_predicted_probs,
                     open_trade, open_trade_pnl_pct, total_pnl_pct, trades_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    datetime.now(timezone.utc),
                    symbol,
                    current_price,
                    last_predicted_class,
                    probs_json,
                    open_trade,
                    open_trade_pnl_pct,
                    total_pnl_pct,
                    trades_count
                ))
                
                conn.commit()
    
    def get_recent_trades(self, symbol: str = None, limit: int = 20) -> List[Dict]:
        """Get recent closed trades"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            query = "SELECT * FROM trades WHERE exit_time IS NOT NULL"
            params = []
            
            if symbol:
                query += " AND symbol = ?"
                params.append(symbol)
            
            query += " ORDER BY exit_time DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(query, params)
            
            trades = []
            for row in cursor.fetchall():
                trade = dict(row)
                if trade['predicted_probs']:
                    trade['predicted_probs'] = json.loads(trade['predicted_probs'])
                trades.append(trade)
            
            return trades
    
    def get_open_trades(self, symbol: str = None) -> List[Dict]:
        """Get currently open trades"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            query = "SELECT * FROM trades WHERE exit_time IS NULL"
            params = []
            
            if symbol:
                query += " AND symbol = ?"
                params.append(symbol)
            
            query += " ORDER BY entry_time DESC"
            
            cursor.execute(query, params)
            
            trades = []
            for row in cursor.fetchall():
                trade = dict(row)
                if trade['predicted_probs']:
                    trade['predicted_probs'] = json.loads(trade['predicted_probs'])
                trades.append(trade)
            
            return trades
    
    def get_latest_metrics(self, symbol: str = None, limit: int = 1) -> List[Dict]:
        """Get latest metrics snapshot"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            query = "SELECT * FROM live_metrics"
            params = []
            
            if symbol:
                query += " WHERE symbol = ?"
                params.append(symbol)
            
            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(query, params)
            
            metrics = []
            for row in cursor.fetchall():
                metric = dict(row)
                if metric['last_predicted_probs']:
                    metric['last_predicted_probs'] = json.loads(metric['last_predicted_probs'])
                metrics.append(metric)
            
            return metrics
    
    def get_all_symbols_metrics(self) -> Dict[str, Dict]:
        """Get latest metrics for all symbols"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT DISTINCT symbol FROM live_metrics
                ORDER BY symbol
            """)
            
            symbols = [row[0] for row in cursor.fetchall()]
            result = {}
            
            for symbol in symbols:
                cursor.execute("""
                    SELECT * FROM live_metrics
                    WHERE symbol = ?
                    ORDER BY timestamp DESC
                    LIMIT 1
                """, (symbol,))
                
                row = cursor.fetchone()
                if row:
                    metric = dict(row)
                    if metric['last_predicted_probs']:
                        metric['last_predicted_probs'] = json.loads(metric['last_predicted_probs'])
                    result[symbol] = metric
            
            return result
    
    def get_stats(self, symbol: str = None) -> Dict:
        """Get trading statistics"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            query_where = ""
            params = []
            if symbol:
                query_where = " WHERE symbol = ?"
                params.append(symbol)
            
            # Total trades
            cursor.execute(f"SELECT COUNT(*) FROM trades{query_where}", params)
            total_trades = cursor.fetchone()[0]
            
            # Winning trades
            cursor.execute(f"SELECT COUNT(*) FROM trades WHERE pnl_pct > 0{' AND symbol = ?' if symbol else ''}", params)
            winning_trades = cursor.fetchone()[0]
            
            # Total P&L
            cursor.execute(f"SELECT SUM(pnl_pct) FROM trades WHERE pnl_pct IS NOT NULL{' AND symbol = ?' if symbol else ''}", params)
            total_pnl = cursor.fetchone()[0] or 0.0
            
            win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0
            avg_pnl = (total_pnl / total_trades) if total_trades > 0 else 0.0
            
            return {
                'total_trades': total_trades,
                'winning_trades': winning_trades,
                'losing_trades': total_trades - winning_trades,
                'win_rate': win_rate,
                'total_pnl': total_pnl,
                'avg_pnl': avg_pnl
            }


# Global instance
history_db = TradingHistory()
