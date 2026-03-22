"""
trading/coin_trader.py
======================
Single coin trading logic with independent ML model and CE strategy
"""

import numpy as np
import pandas as pd
import time
import threading
from datetime import datetime, timezone
from typing import Dict, Optional
from ML.live_predictor import CryptoBreakoutPredictor
from strategies.chandelier_exit import ChandelierExit
from core.binance_client import get_binance_current_price, get_binance_latest_candle
from core.roostoo_client import get_roostoo_balance, get_roostoo_position
from core.telegram_bot import send_telegram_message, send_trade_entry_message, send_trade_exit_message
from core.trading_history import history_db
from config.settings import ML_ENABLED, ML_MODEL_DIR, POSITION_SIZE_PCT, TAKE_PROFIT_PCT, STOP_LOSS_PCT


class CoinTrader:
    """
    Handles trading logic for a single cryptocurrency
    Runs independently with its own ML model and CE strategy
    """
    
    def __init__(self, symbol: str, binance_symbol: str, roostoo_pair: str, 
                 model_dir: str, allocation_pct: float = 0.2):
        """
        Args:
            symbol: Display name (e.g., 'BTC')
            binance_symbol: Binance symbol (e.g., 'BTCUSDT')
            roostoo_pair: Roostoo pair (e.g., 'BTC/USD')
            model_dir: Path to this coin's ML models
            allocation_pct: % of total balance to allocate (0.2 = 20%)
        """
        self.symbol = symbol
        self.binance_symbol = binance_symbol
        self.roostoo_pair = roostoo_pair
        self.model_dir = model_dir
        self.allocation_pct = allocation_pct
        
        # Trading state
        self.is_running = False
        self.thread = None
        self.df = None
        self.strategy = None
        self.ml_predictor = None
        
        # Statistics
        self.trades_count = 0
        self.total_pnl = 0.0
        self.last_update = None
        self.last_pnl_update = None  # Track last P&L update time
        
        # Trade tracking for history
        self.current_trade_id = None
        self.prev_position_size = 0
        self.prev_entry_price = 0
        self.prev_predicted_class = None
        self.prev_predicted_probs = None
        
        print(f"✅ {symbol} trader initialized")
    
    def initialize(self):
        """Load ML model and initialize CE strategy with ATR pre-initialization"""
        try:
            # Load ML predictor for this coin
            if ML_ENABLED:
                self.ml_predictor = CryptoBreakoutPredictor(model_dir=self.model_dir)
                print(f"✅ {self.symbol}: ML model loaded from {self.model_dir}")

            # Load historical data
            self.df = self._load_historical_data()

            # Initialize CE strategy
            self.strategy = ChandelierExit(self.df)
            self.strategy.symbol = self.roostoo_pair  # Set symbol after init

            # ✅ PRE-INITIALIZE ATR (so no need to wait 22 bars)
            self._initialize_atr()
            
            # ✅ CHECK FOR EXISTING POSITION ON STARTUP
            self._check_existing_position()

            self.last_update = datetime.now(timezone.utc)
            self.last_pnl_update = None  # Reset P&L update tracker
            print(f"✅ {self.symbol}: Strategy initialized with ATR pre-initialized")

        except Exception as e:
            print(f"❌ {self.symbol}: Initialization failed: {e}")
            raise
    
    def _check_existing_position(self):
        """Check if there's an existing position from before restart"""
        try:
            pos_size, avg_price = get_roostoo_position(pair=self.strategy.symbol)
            
            if pos_size > 0.001:
                print(f"🔍 {self.symbol}: EXISTING POSITION DETECTED!")
                print(f"   Position Size: {pos_size}")
                print(f"   Avg Entry Price: ${avg_price}")
                
                # Set strategy to track this position
                self.strategy.position_size = pos_size
                self.strategy.entry_price = avg_price
                self.strategy.has_order = True
                
                # Get current price for P&L calculation
                current_price = get_binance_current_price(self.binance_symbol)
                self.strategy.current_price = current_price
                
                # Calculate current P&L
                current_pnl = ((current_price - avg_price) / avg_price) * 100
                print(f"   Current Price: ${current_price}")
                print(f"   Current P&L: {current_pnl:+.2f}%")
                print(f"   ✅ Position recovery complete - P&L tracking resumed")
                
                # Send POSITION RECOVERED notification
                send_telegram_message(
                    f"🔄 <b>POSITION RECOVERED ON RESTART</b>\n"
                    f"├─ Symbol: {self.symbol}\n"
                    f"├─ Position Size: {pos_size}\n"
                    f"├─ Entry Price: ${avg_price}\n"
                    f"├─ Current Price: ${current_price}\n"
                    f"├─ Current P&L: {current_pnl:+.2f}%\n"
                    f"└─ Bot restarted - P&L tracking resumed"
                )
                
                # Send P&L UPDATE notification (as if it's a regular 15min update)
                trend = "UPTREND" if self.strategy.is_uptrend else "DOWNTREND"
                send_telegram_message(
                    f"📊 <b>{self.symbol} P&L UPDATE</b>\n"
                    f"├─ Side: LONG\n"
                    f"├─ Entry: ${avg_price:.2f}\n"
                    f"├─ Current: ${current_price:.2f}\n"
                    f"├─ P&L: {current_pnl:+.2f}%\n"
                    f"├─ Supertrend: {trend}\n"
                    f"└─ Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                )
                
                print(f"📊 P&L update sent for recovered position")
            else:
                print(f"🔍 {self.symbol}: No existing position found")
        except Exception as e:
            print(f"⚠️  {self.symbol}: Error checking existing position: {e}")
    
    def _load_historical_data(self, days_back=3, interval='15m'):
        """Load historical candles for this coin"""
        from data.fetcher import load_binance_historical_data
        
        df = load_binance_historical_data(
            symbol=self.binance_symbol,
            interval=interval,
            days_back=days_back
        )
        return df
    
    def _initialize_atr(self):
        """Pre-initialize ATR and TrueRangeList from historical data"""
        if self.strategy and len(self.df) >= self.strategy.ATR_period + 1:
            # Calculate TrueRangeList from historical data
            self.strategy.TrueRangeList = []
            for i in range(1, len(self.df)):
                high = self.df['High'].iloc[i]
                low = self.df['Low'].iloc[i]
                prev_close = self.df['Close'].iloc[i-1]
                tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
                self.strategy.TrueRangeList.append(tr)
            
            # Now calculate ATR from TrueRangeList
            if len(self.strategy.TrueRangeList) >= self.strategy.ATR_period:
                self.strategy.atr = np.mean(
                    self.strategy.TrueRangeList[-self.strategy.ATR_period:]
                )
                
                # Initialize CE levels from historical data
                closes = self.df['Close'].iloc[-self.strategy.ATR_period:]
                highest = np.max(closes)
                lowest = np.min(closes)
                ce_atr = self.strategy.ATR_muti * self.strategy.atr
                
                self.strategy.long_stop_prev = highest - ce_atr
                self.strategy.short_stop_prev = lowest + ce_atr
                
                # Initialize Supertrend
                if len(self.strategy.TrueRangeList) >= self.strategy.st_atr_period:
                    tr_list = self.strategy.TrueRangeList[-self.strategy.st_atr_period:]
                    self.strategy.st_atr = np.mean(tr_list)
                    
                    high = self.df['High'].iloc[-1]
                    low = self.df['Low'].iloc[-1]
                    close = self.df['Close'].iloc[-1]
                    hl2 = (high + low) / 2
                    
                    self.strategy.prev_up = hl2 - (self.strategy.st_factor * self.strategy.st_atr)
                    self.strategy.prev_down = hl2 + (self.strategy.st_factor * self.strategy.st_atr)
                    self.strategy.prev_superTrend = self.strategy.prev_up
                    self.strategy.is_uptrend = close > self.strategy.prev_up
                
                print(f"✅ {self.symbol}: ATR pre-initialized at {self.strategy.atr:.4f}")
                print(f"✅ {self.symbol}: TrueRangeList populated with {len(self.strategy.TrueRangeList)} values")
            else:
                print(f"⚠️ {self.symbol}: TrueRangeList has {len(self.strategy.TrueRangeList)} values, need {self.strategy.ATR_period}")
        else:
            print(f"⚠️ {self.symbol}: Not enough historical data ({len(self.df)} bars, need {self.strategy.ATR_period + 1})")
            
    def start(self):
        """Start trading loop in separate thread"""
        if self.is_running:
            print(f"⚠️ {self.symbol}: Already running")
            return
        
        self.is_running = True
        self.thread = threading.Thread(target=self._trading_loop, daemon=True)
        self.thread.start()
        print(f"🚀 {self.symbol}: Trading started")
    
    def stop(self):
        """Stop trading loop"""
        self.is_running = False
        if self.thread:
            self.thread.join(timeout=5)
        print(f"⏹️ {self.symbol}: Trading stopped")
    
    def _trading_loop(self):
        """Main trading loop for this coin"""
        from core.utils import wait_until_next_quarter_hour
        
        while self.is_running:
            try:
                # Wait for next 15min candle
                wait_until_next_quarter_hour()
                time.sleep(3)
                
                # Fetch latest candle
                latest_df = self._fetch_latest_candle()
                
                if latest_df.empty:
                    print(f"⚠️ {self.symbol}: No new data, skipping")
                    continue
                
                # Update dataframe
                self.df = pd.concat([self.df, latest_df])
                self.strategy.df = self.df
                
                # Get current price
                current_price = get_binance_current_price(self.binance_symbol)
                self.strategy.current_price = current_price

                # ✅ GET ML PREDICTION BEFORE EXECUTING STRATEGY
                self._get_and_set_ml_prediction()

                # Execute strategy
                self.strategy.next()

                # ✅ P&L UPDATE EVERY 15 MINUTES (every bar) for open trades
                self._update_pnl_if_open()

                # ✅ ML PREDICTION TERMINAL OUTPUT EVERY 15 MINUTES
                self._print_ml_prediction()

                # Update statistics
                self.last_update = datetime.now(timezone.utc)
                
            except Exception as e:
                print(f"❌ {self.symbol}: Error in trading loop: {e}")
                # ✅ Send error notification to Telegram
                send_telegram_message(
                    f"❌ <b>{self.symbol} Trading Error</b>\n"
                    f"├─ Error: {str(e)}\n"
                    f"└─ Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
                )
                time.sleep(60)
    
    def _update_pnl_if_open(self):
        """Send P&L update every 15 minutes if trade is open (Telegram + Terminal)"""
        # Get actual position from Roostoo
        actual_pos_size, actual_avg_price = get_roostoo_position(pair=self.strategy.symbol)

        # Only send P&L update if there's actually a position
        if actual_pos_size > 0.001:
            # Get entry price - use Roostoo value if available, otherwise check database
            entry_price = actual_avg_price if (actual_avg_price and actual_avg_price > 0) else 0
            
            # If Roostoo doesn't return entry price, query database
            if entry_price == 0:
                try:
                    open_trades = history_db.get_open_trades_with_pnl()
                    for trade in open_trades:
                        if trade['symbol'] == self.strategy.symbol:
                            entry_price = trade.get('entry_price', 0)
                            print(f"📝 {self.symbol}: Entry price ${entry_price} recovered from database")
                            break
                except Exception as e:
                    print(f"⚠️  {self.symbol}: Error getting entry price from DB: {e}")
            
            # Skip if we still don't have entry price
            if entry_price == 0:
                print(f"⚠️  {self.symbol}: Cannot send P&L update - entry price is 0")
                return
            
            current_price = self.strategy.current_price
            # LONG only (no shorting)
            current_pl_pct = ((current_price - entry_price) / entry_price) * 100

            side = "LONG"  # Always LONG since we don't short
            trend = "UPTREND" if self.strategy.is_uptrend else "DOWNTREND"

            # Send P&L update to Telegram (every bar = every 15min for open trades)
            pnl_message = (
                f"📊 <b>{self.symbol} P&L UPDATE</b>\n"
                f"├─ Side: {side}\n"
                f"├─ Entry: ${entry_price:.2f}\n"
                f"├─ Current: ${current_price:.2f}\n"
                f"├─ P&L: {current_pl_pct:+.2f}%\n"
                f"├─ Supertrend: {trend}\n"
                f"└─ Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
            )
            send_telegram_message(pnl_message)

            # Print comprehensive P&L to terminal
            print(f"\n{'='*50}")
            print(f"📊 {self.symbol} P&L UPDATE @ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
            print(f"{'='*50}")
            print(f"   Side: {side}")
            print(f"   Entry Price: ${entry_price:.2f}")
            print(f"   Current Price: ${current_price:.2f}")
            print(f"   P&L: {current_pl_pct:+.2f}%")
            print(f"   Supertrend: {trend}")
            print(f"   CE Direction: {self.strategy.dir}")
            if self.strategy.tp_price and self.strategy.sl_price:
                tp_distance = ((self.strategy.tp_price - current_price) / current_price) * 100
                sl_distance = ((current_price - self.strategy.sl_price) / current_price) * 100
                print(f"   TP: ${self.strategy.tp_price:.2f} ({tp_distance:+.2f}% away)")
                print(f"   SL: ${self.strategy.sl_price:.2f} ({sl_distance:+.2f}% away)")
            print(f"{'='*50}\n")
    
    def _fetch_latest_candle(self):
        """Fetch latest candle for this coin"""
        from data.fetcher import get_latest_binance_candle

        return get_latest_binance_candle(
            symbol=self.binance_symbol,
            interval='15m'
        )

    def _print_ml_prediction(self):
        """Print comprehensive ML prediction to terminal and log to database (NO Telegram)"""
        if not ML_ENABLED or self.ml_predictor is None:
            return

        try:
            # Get ML prediction using coin-specific model
            ccxt_symbol = f"{self.symbol}/USDT"
            ml_prediction = self.ml_predictor.predict(ccxt_symbol, timeframe='15m')

            probs = ml_prediction['probabilities']
            breakout_prob = probs[1] + probs[2] + probs[3]
            tp_pct = TAKE_PROFIT_PCT.get(ml_prediction['predicted_class'], 0.01) * 100
            sl_pct = STOP_LOSS_PCT.get(ml_prediction['predicted_class'], 0.015) * 100

            # ✅ LOG ML PREDICTION TO DATABASE (NO TELEGRAM)
            ml_prediction['tp_target'] = tp_pct
            ml_prediction['sl_limit'] = sl_pct
            history_db.record_ml_prediction(self.symbol, ml_prediction)

            # Print to terminal
            print(f"\n{'='*70}")
            print(f"🔮 ML PREDICTION - {self.symbol} @ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
            print(f"{'='*70}")
            print(f"   Price: ${ml_prediction['price']:.2f}")
            print(f"   Predicted Class: {ml_prediction['predicted_class']}")
            print(f"   Breakout Probability: {breakout_prob*100:.1f}%")
            print(f"   ")
            print(f"   ┌─ Class Probabilities:")
            print(f"   ├─ Class 0 (No Trade):     {probs[0]*100:6.2f}%")
            print(f"   ├─ Class 1 (1-3% TP):      {probs[1]*100:6.2f}%")
            print(f"   ├─ Class 2 (3-5% TP):      {probs[2]*100:6.2f}%")
            print(f"   └─ Class 3 (>5% TP):       {probs[3]*100:6.2f}%")
            print(f"   ")
            print(f"   ┌─ Trading Metrics:")
            print(f"   ├─ Recommendation: {ml_prediction['recommendation']}")
            print(f"   ├─ Suggested Size: {ml_prediction['position_size_pct']*100:.1f}%")
            print(f"   ├─ TP Target: {tp_pct:.1f}%")
            print(f"   ├─ SL Limit: {sl_pct:.2f}%")
            print(f"   └─ Execution Time: {ml_prediction['execution_time_ms']:.0f}ms")
            print(f"{'='*70}\n")

        except Exception as e:
            print(f"⚠️  {self.symbol}: ML prediction failed: {e}")

    def _get_and_set_ml_prediction(self):
        """Get ML prediction and set it in strategy for entry filtering"""
        if not ML_ENABLED or self.ml_predictor is None:
            self.strategy.ml_prediction = None
            return

        try:
            ccxt_symbol = f"{self.symbol}/USDT"
            ml_prediction = self.ml_predictor.predict(ccxt_symbol, timeframe='15m')
            self.strategy.ml_prediction = ml_prediction
            
            # Debug: Show breakout probability for this candle
            probs = ml_prediction['probabilities']
            breakout_prob = probs[1] + probs[2] + probs[3]
            print(f"🔮 {self.symbol} ML Update @ {datetime.now(timezone.utc).strftime('%H:%M:%S')} | Breakout: {breakout_prob*100:.1f}% | Class: {ml_prediction['predicted_class']}")
            
        except Exception as e:
            print(f"⚠️  {self.symbol}: ML prediction failed: {e}")
            self.strategy.ml_prediction = None

    def get_status(self) -> Dict:
        """Get current trading status"""
        return {
            'symbol': self.symbol,
            'is_running': self.is_running,
            'last_update': self.last_update,
            'trades_count': self.trades_count,
            'total_pnl': self.total_pnl,
            'current_position': self.strategy.position_size if self.strategy else 0,
            'current_price': self.strategy.current_price if self.strategy else 0,
            'has_open_trade': self.strategy.has_order if self.strategy else False,
            'signal_stats': {
                'ce_signals': self.strategy.ce_signals_count if self.strategy else 0,
                'ml_approved': self.strategy.ml_approved_count if self.strategy else 0,
                'trades_executed': self.strategy.trades_executed_count if self.strategy else 0
            } if self.strategy else None
        }