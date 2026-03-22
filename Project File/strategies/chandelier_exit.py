import numpy as np
import pandas as pd
from datetime import datetime, timezone
from typing import Optional
import time
import threading

# ML Imports (only should_trade utility function)
from ML.live_predictor import should_trade
from config.settings import ML_MODEL_DIR, ML_CONFIDENCE_THRESHOLD, ML_ENABLED
from config.settings import TP_SL_ENABLED, STOP_LOSS_PCT, TAKE_PROFIT_PCT, TP_SL_CHECK_INTERVAL, LIMIT_ORDER_AT_TP

# Roostoo Broker Imports (TRADING)
from core.roostoo_client import (
    get_roostoo_position,
    get_roostoo_balance,
    calculate_roostoo_order_size,
    place_roostoo_order,
    close_roostoo_position,
    get_roostoo_current_price,
    cancel_roostoo_order
)

# Binance Data Imports (DATA ONLY)
from core.binance_client import get_binance_current_price

# Telegram & Utils
from core.telegram_bot import (
    send_telegram_message,
    send_ml_prediction_message,
    send_tp_triggered_message,
    send_sl_triggered_message,
    send_tp_sl_update_message
)
from core.utils import is_us_market_open
from config.settings import (
    POSITION_SIZE_PCT,
    ROOSTOO_PAIR,
    ROOSTOO_BASE_CURRENCY,
    TP_SL_ENABLED,
    STOP_LOSS_PCT,
    TAKE_PROFIT_PCT,
    TP_SL_CHECK_INTERVAL,
    LIMIT_ORDER_AT_TP
)

# ✅ REMOVED: Module-level ml_predictor (not used - each CoinTrader has its own)
# ML predictions are now handled by CoinTrader.ml_predictor

class ChandelierExit:
    def __init__(self, df, size=POSITION_SIZE_PCT, symbol=None):
        self.df = df
        self.symbol = symbol if symbol else ROOSTOO_PAIR
        self.size = size  # Fraction of available balance to use
        self.position_size = 0.0  # Track quantity (positive=long, negative=short)
        self.entry_price = 0.0
        self.has_order = False
        
        # Your existing variables...
        self.TrueRangeList = []
        self.atr_averageList = []
        self.ATR_period = 22
        self.ATR_muti = 2.0
        self.ATR_muti_USopen = 2.0
        self.atr = None

        # CE variables...
        self.use_close = True
        self.long_stop_prev = None
        self.short_stop_prev = None
        self.dir = 0
        self.prev_dir = 0

        # Supertrend variables...
        self.st_atr_period = 2
        self.st_factor = 0.5
        self.prev_up = 0
        self.prev_down = 0
        self.st_atr_prev = None
        self.st_atr = None
        self.prev_lowerBand = None
        self.prev_upperBand = None
        self.prev_superTrend = None

        # Other...
        self.close_prev = 0
        self.current_close = 0
        self.current_price = 0.0
        self.buy_signal = False
        self.sell_signal = False
        self.is_uptrend = False

        # TP/SL tracking variables
        self.tp_price = None
        self.sl_price = None
        self.predicted_class_on_entry = None
        self.tp_order_id = None
        self.sl_order_id = None
        self.tp_limit_placed = False
        
        # Ladder TP tracking
        self.tp_ladder_levels = []  # List of TP levels based on class
        self.tp_ladder_orders = {}  # Dict: level_pct -> {order_id, filled, size}
        self.current_tp_level = 0   # Current highest TP level reached
        self.original_position_size = 0  # Store entry position size

        # Real-time monitoring
        self.monitoring_thread = None
        self.stop_monitoring = False

        # Debug
        self.bar_count = 0
        self.entry_bar_count = 0  # Track which bar we entered on
        self.max_hold_candles = 20  # Maximum candles to hold trade
        
        # Signal tracking counters
        self.ce_signals_count = 0  # Total CE signals generated
        self.ml_approved_count = 0  # Signals that passed ML filter
        self.trades_executed_count = 0  # Trades actually executed

        # ML prediction (set by CoinTrader before next() call)
        self.ml_prediction = None

        # TP/SL tracking variables (ADD AFTER self.bar_count = 0)
        self.tp_price = None
        self.sl_price = None
        self.predicted_class_on_entry = None
        self.tp_order_id = None
        self.tp_limit_placed = False

        # Real-time monitoring (ADD THESE)
        self.monitoring_thread = None
        self.stop_monitoring = False

    def check_has_open_position(self):
        """Check if there's actually an open position by checking Roostoo balance"""
        try:
            # Get actual position from Roostoo
            pos_size, _ = get_roostoo_position(pair=self.symbol)
            has_pos = pos_size > 0.001  # Consider it open if position > 0.001
            print(f"🔍 Position check for {self.symbol}: Size={pos_size}, Has_Position={has_pos}")
            return has_pos
        except Exception as e:
            print(f"⚠️  Error checking position: {e}")
            return False

    def next(self):
        self.bar_count += 1
        current_time = self.df.index[-1]

        if len(self.df) < 2:
            print(f"{current_time} - Not enough data: {len(self.df)} bars")
            return

        high = self.df['High'].iloc[-1]
        low = self.df['Low'].iloc[-1]
        prev_close = self.df['Close'].iloc[-2]

        tr1 = high - low
        tr2 = abs(high - prev_close)
        tr3 = abs(low - prev_close)
        true_range = max(tr1, tr2, tr3)
        self.TrueRangeList.append(true_range)

        print(f"\n{current_time} - Bar {self.bar_count}")
        print(f"Data bars: {len(self.df)}, TR list: {len(self.TrueRangeList)}")

        # ATR calculation
        atr_ready = False
        if self.atr is None and len(self.TrueRangeList) == self.ATR_period:
            self.atr = sum(self.TrueRangeList[-self.ATR_period:]) / self.ATR_period
            atr_ready = True
            print(f"ATR22: {self.atr:.4f}")
        elif self.atr is not None:
            self.atr = (self.atr * (self.ATR_period - 1) + true_range) / self.ATR_period
            atr_ready = True
            print(f"ATR22: {self.atr:.4f}")
        else:
            print(f"ATR not ready: {len(self.TrueRangeList)}/{self.ATR_period + 1} bars needed")

        # CE calculation (replace self.data with self.df)
        ce_ready = False
        if atr_ready and len(self.df) >= self.ATR_period:
            if self.use_close:
                closes = self.df['Close'].iloc[-self.ATR_period:]
                highest = np.max(closes)
                lowest = np.min(closes)
            else:
                highs = self.df['High'].iloc[-self.ATR_period:]
                lows = self.df['Low'].iloc[-self.ATR_period:]
                highest = np.max(highs)
                lowest = np.min(lows)

            Actual_ATR_muti = None
            if is_us_market_open():
                Actual_ATR_muti = self.ATR_muti_USopen
            else:
                Actual_ATR_muti = self.ATR_muti
            ce_atr = Actual_ATR_muti * self.atr
            long_stop = highest - ce_atr
            short_stop = lowest + ce_atr

            if self.long_stop_prev is None:
                self.long_stop_prev = long_stop
                self.short_stop_prev = short_stop
                print("CE initialized")
            else:
                self.close_prev = self.df['Close'].iloc[-2]
                if self.close_prev > self.long_stop_prev:
                    long_stop = max(long_stop, self.long_stop_prev)
                if self.close_prev < self.short_stop_prev:
                    short_stop = min(short_stop, self.short_stop_prev)

            self.current_close = self.df['Close'].iloc[-1]
            self.prev_dir = self.dir

            if self.current_close > short_stop:
                self.dir = 1
            elif self.current_close < long_stop:
                self.dir = -1
            else:
                self.dir = self.prev_dir

            self.long_stop_prev = long_stop
            self.short_stop_prev = short_stop

            self.buy_signal = (self.dir == 1) and (self.prev_dir == -1)
            self.sell_signal = (self.dir == -1) and (self.prev_dir == 1)
            print(f"CE - Dir: {self.dir}, Buy: {self.buy_signal}, Sell: {self.sell_signal}")
        else:
            print(f"CE not ready - ATR: {atr_ready}, Data bars: {len(self.df)}/{self.ATR_period}")

        # Supertrend
        if len(self.TrueRangeList) >= self.st_atr_period:
            # RMA ATR for Supertrend
            if self.st_atr is None:
                    self.st_atr = np.mean(self.TrueRangeList[-self.st_atr_period:])
            else:
                self.st_atr = (self.st_atr * (self.st_atr_period - 1) + true_range) / self.st_atr_period

            hl2 = (high + low) / 2
            upperBand = hl2 + self.st_factor * self.st_atr
            lowerBand = hl2 - self.st_factor * self.st_atr

            # Ratcheting logic
            prevLowerBand = self.prev_lowerBand if self.prev_lowerBand is not None else lowerBand
            prevUpperBand = self.prev_upperBand if self.prev_upperBand is not None else upperBand

            if lowerBand > prevLowerBand or self.close_prev < prevLowerBand:
                pass
            else:
                lowerBand = prevLowerBand

            if upperBand < prevUpperBand or self.close_prev > prevUpperBand:
                pass
            else:
                upperBand = prevUpperBand

            # Direction logic
            _direction = None
            prevSuperTrend = self.prev_superTrend if self.prev_superTrend is not None else np.nan
            if self.st_atr_prev is None or np.isnan(self.st_atr_prev):
                _direction = 1
            else:
                if prevSuperTrend == prevUpperBand:
                    _direction = -1 if self.current_close > upperBand else 1
                else:
                    _direction = 1 if self.current_close < lowerBand else -1

            # Supertrend value
            supertrend = lowerBand if _direction == -1 else upperBand

            # Update for next bar
            self.prev_lowerBand = lowerBand
            self.prev_upperBand = upperBand
            self.prev_superTrend = supertrend
            self.st_atr_prev = self.st_atr
            self.is_uptrend = _direction == -1  # Critical for exit logic
            trend_status = "UPTREND" if self.is_uptrend else "DOWNTREND"
            print(f"Supertrend: {supertrend:.4f}, Direction: {_direction}, Status: {trend_status}")

        # TRADING LOGIC
        print(f"Position size: {self.position_size}, has_order: {self.check_has_open_position()}")

        current_price = self.current_price  # Use live price for trading decisions

        # === TIME-BASED EXIT (Max 20 candles) ===
        if self.check_has_open_position() and (self.bar_count - self.entry_bar_count) >= self.max_hold_candles:
            # Held for 20 candles, exit if not profitable enough
            current_pl_pct = ((current_price - self.entry_price) / self.entry_price) * \
                            (1 if self.position_size > 0 else -1) * 100
            
            if current_pl_pct < 0.5:  # Less than 0.5% profit
                final_pl_pct = current_pl_pct
                if self.position_size > 0:
                    close_roostoo_position(pair=self.symbol, side="SELL")
                else:
                    close_roostoo_position(pair=self.symbol, side="BUY")
                
                self.position_size = 0
                self.has_order = False
                self.entry_bar_count = 0
                reason = f"Time Exit ({self.max_hold_candles} candles)"
                
                close_message = (
                    f"⏰ <b>TIME EXIT</b>\n"
                    f"├─ Symbol: {self.symbol}\n"
                    f"├─ Reason: {reason}\n"
                    f"├─ Exit Price: ${current_price:.2f}\n"
                    f"├─ Entry Price: ${self.entry_price:.2f}\n"
                    f"├─ P&L: {final_pl_pct:+.2f}%\n"
                    f"└─ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}"
                )
                print(f"⏰ TIME EXIT → {reason} @ {current_price:.2f} | P&L: {final_pl_pct:+.2f}%")
                send_telegram_message(close_message)

        # === EXIT LONG ===
        if self.position_size > 0:
            in_profit = (current_price > self.entry_price)
            if self.sell_signal or (not self.is_uptrend and in_profit):
                final_pl_pct = ((current_price - self.entry_price) / self.entry_price) * (1 if self.position_size > 0 else -1) * 100
                close_roostoo_position(pair=self.symbol, side="SELL")
                self.position_size = 0
                self.has_order = False
                self.long_stop_prev = None
                self.short_stop_prev = None
                self.dir = 0
                self.prev_dir = 0
                reason = "CE Sell Signal" if self.sell_signal else "Supertrend Down (in profit)"
                close_message = (
                    f"🚨 <b>CLOSED LONG POSITION</b>\n"
                    f"├─ Symbol: {self.symbol}\n"
                    f"├─ Reason: {reason}\n"
                    f"├─ Exit Price: ${current_price:.2f}\n"
                    f"├─ Entry Price: ${self.entry_price:.2f}\n"
                    f"├─ P&L: {final_pl_pct:+.2f}%\n"
                    f"└─ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}"
                )
                print(f"CLOSED LONG → {reason} @ {current_price:.2f} | P&L: {final_pl_pct:+.2f}%")
                send_telegram_message(close_message)

        # === EXIT SHORT ===
        if self.position_size < 0:
            in_profit = current_price < self.entry_price
            if self.buy_signal or (self.is_uptrend and in_profit):
                final_pl_pct = ((current_price - self.entry_price) / self.entry_price) * (1 if self.position_size > 0 else -1) * 100
                close_roostoo_position(pair=self.symbol, side="BUY")
                self.position_size = 0
                self.has_order = False
                self.long_stop_prev = None
                self.short_stop_prev = None
                self.dir = 0
                self.prev_dir = 0
                reason = "CE Buy Signal" if self.buy_signal else "Supertrend Up (in profit)"
                close_message = (
                    f"🚨 <b>CLOSED SHORT POSITION</b>\n"
                    f"├─ Symbol: {self.symbol}\n"
                    f"├─ Reason: {reason}\n"
                    f"├─ Exit Price: ${current_price:.2f}\n"
                    f"├─ Entry Price: ${self.entry_price:.2f}\n"
                    f"├─ P&L: {final_pl_pct:+.2f}%\n"
                    f"└─ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}"
                )
                print(f"CLOSED SHORT → {reason} @ {current_price:.2f} | P&L: {final_pl_pct:+.2f}%")
                send_telegram_message(close_message)

        # === ENTRY RULES (only if no position) ===
        # Check ACTUAL balance/position instead of boolean flag
        if not self.check_has_open_position():
            # Get position info from Roostoo instead of balance
            pos_size, _ = get_roostoo_position(pair=self.symbol)

            if pos_size <= 0.001:  # No existing position
                usdt_balance = get_roostoo_balance(ROOSTOO_BASE_CURRENCY)
                if usdt_balance <= 0:
                    print("No USDT balance for entry")
                    return
            
                # Calculate position size based on available balance and current price
                entry_value = usdt_balance * self.size
                if current_price <= 0:
                    print(f"Invalid price: {current_price}. Skipping trade.")
                    return

                # ===== ML FILTER: Get prediction before entry =====
                # ML prediction is passed from CoinTrader via self.ml_prediction
                ml_prediction = getattr(self, 'ml_prediction', None)
                ml_approved = False
                ml_position_size_pct = 0.02  # Default 2%

                if ml_prediction is not None and ML_ENABLED:
                    try:
                        # Check breakout probability sum >= 0.9
                        ml_approved = should_trade(ml_prediction, min_breakout_probability=ML_CONFIDENCE_THRESHOLD)
                        ml_position_size_pct = ml_prediction['position_size_pct']

                        # Print detailed probability breakdown
                        probs = ml_prediction['probabilities']
                        breakout_prob = probs[1] + probs[2] + probs[3]
                        print(f"🔮 ML Prediction:")
                        print(f"   Class 0 (No Trade): {probs[0]*100:.1f}%")
                        print(f"   Class 1 (1-3%):     {probs[1]*100:.1f}%")
                        print(f"   Class 2 (3-5%):     {probs[2]*100:.1f}%")
                        print(f"   Class 3 (>5%):      {probs[3]*100:.1f}%")
                        print(f"   Breakout Sum:       {breakout_prob*100:.1f}% (threshold: 90%)")
                        print(f"   Highest Prob Class: {ml_prediction['highest_prob_class']}")
                        print(f"   Approved: {ml_approved}")
                    except Exception as e:
                        print(f"⚠️  ML prediction failed: {e}")
                        ml_approved = False
                else:
                    ml_approved = False  # ML disabled or no prediction, use CE only

                # Count CE signals (buy or sell)
                if self.buy_signal or self.sell_signal:
                    self.ce_signals_count += 1
                    if ml_approved:
                        self.ml_approved_count += 1
                    print(f"📊 CE Signal #{self.ce_signals_count}: Buy={self.buy_signal}, Sell={self.sell_signal}, ML_Approved={ml_approved} ({self.ml_approved_count}/{self.ce_signals_count} approved)")

                # LONG: CE buy signal
                if self.buy_signal and ml_approved:
                    self.trades_executed_count += 1
                    actual_size_pct = ml_position_size_pct if ml_prediction else self.size
                    entry_value = usdt_balance * actual_size_pct

                    predicted_class = ml_prediction['predicted_class'] if ml_prediction else 1

                    print(f"🎯 Calculated entry value: ${entry_value:.2f} of ${usdt_balance:.2f} balance")
                    contract_size_str = calculate_roostoo_order_size(
                        usd_amount=entry_value,
                        coin_price=current_price,
                    )
                    print(f"\n🚀 LONG ENTRY SIGNAL @ ${current_price:.2f}")
                    print(f"📊 CE Buy Signal + Supertrend Up confirmed")
                    print(f"💰 Order value: ${entry_value:.2f} ({contract_size_str} contracts)")
                    place_roostoo_order(
                        pair=self.symbol,
                        side="BUY",
                        order_type="MARKET",
                        quantity=contract_size_str
                    )
                    # Update position after order
                    self.position_size, _ = get_roostoo_position(pair=self.symbol)
                    if current_price > 0:
                        self.entry_price = current_price
                    else:
                        print(f"⚠️ WARNING: Invalid current_price for entry! Using fallback.")
                        self.entry_price = 0.01
                    self.has_order = True

                    # Track entry bar for time-based exit
                    self.entry_bar_count = self.bar_count

                    # Store original position size for ladder calculations
                    self.original_position_size = self.position_size

                    # ✅ RECORD TRADE ENTRY TO DATABASE
                    try:
                        from core.trading_history import history_db
                        print(f"📝 Recording trade entry: {self.symbol} @ ${self.entry_price}")
                        trade_id = history_db.record_trade_entry(
                            symbol=self.symbol,
                            entry_price=self.entry_price,
                            side='LONG',
                            predicted_class=ml_prediction.get('predicted_class') if ml_prediction else None,
                            predicted_probs=ml_prediction.get('probabilities') if ml_prediction else None
                        )
                        print(f"📝 Trade entry recorded to database with ID: {trade_id}")
                    except Exception as e:
                        print(f"⚠️  Failed to record trade entry: {e}")
                        import traceback
                        traceback.print_exc()

                    # ===== SET TAKE PROFIT & STOP LOSS (LADDER SYSTEM) =====
                    if TP_SL_ENABLED and ml_prediction:
                        self.predicted_class_on_entry = ml_prediction['highest_prob_class']
                        sl_pct = STOP_LOSS_PCT.get(self.predicted_class_on_entry, 0.015)
                        self.sl_price = self.entry_price * (1 - sl_pct)
                        
                        # Setup LADDER TP levels - 10 levels for ALL classes (1% to 10%)
                        self.tp_ladder_levels = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10]
                        
                        # Set initial TP to first level
                        initial_tp_pct = self.tp_ladder_levels[0]
                        self.tp_price = self.entry_price * (1 + initial_tp_pct)
                        
                        print(f"📊 TP/SL Ladder Set:")
                        print(f"   Highest Prob Class: {self.predicted_class_on_entry}")
                        print(f"   Stop Loss: ${self.sl_price:.2f} (-{sl_pct*100:.1f}%)")
                        print(f"   TP Ladder Levels: {[f'{l*100:.0f}%' for l in self.tp_ladder_levels]}")
                        for i, level in enumerate(self.tp_ladder_levels, 1):
                            tp_price_level = self.entry_price * (1 + level)
                            print(f"   Level {i}: ${tp_price_level:.2f} (+{level*100:.0f}%)")
                        
                        self._start_tp_sl_monitoring()  # Start monitoring TP/SL in a separate thread

                    entry_message = (
                        f"🚀  <b>LONG POSITION OPENED</b>\n"
                        f"├─ Symbol: {self.symbol}\n"
                        f"├─ Entry Price: ${current_price:.2f}\n"
                        f"├─ Size: {contract_size_str} contracts\n"
                        f"├─ Value: ${entry_value:.2f}\n"
                        f"├─ CE Direction: {self.dir}\n"
                        f"├─ Supertrend: {'UPTREND' if self.is_uptrend else 'DOWNTREND'}\n"
                        f"├─ ML Class: {ml_prediction['predicted_class'] if ml_prediction else 'N/A'}\n"
                        f"├─ ML Confidence: {ml_prediction['confidence']*100:.1f}%\n" if ml_prediction else ""
                        f"├─ All Class Probabilities:\n"
                        f"│   ├─ Class 0: {ml_prediction['probabilities'][0]*100:.2f}%\n" if ml_prediction else ""
                        f"│   ├─ Class 1: {ml_prediction['probabilities'][1]*100:.2f}%\n" if ml_prediction else ""
                        f"│   ├─ Class 2: {ml_prediction['probabilities'][2]*100:.2f}%\n" if ml_prediction else ""
                        f"│   └─ Class 3: {ml_prediction['probabilities'][3]*100:.2f}%\n" if ml_prediction else ""
                        f"├─ TP/SL Settings:\n"
                        f"│   ├─ Take Profit: ${self.tp_price:.2f} (+{tp_pct*100:.1f}%)\n" if TP_SL_ENABLED and ml_prediction else ""
                        f"│   └─ Stop Loss: ${self.sl_price:.2f} (-{sl_pct*100:.1f}%)\n" if TP_SL_ENABLED and ml_prediction else ""
                        f"└─ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                    )
                    send_telegram_message(entry_message)

                # SHORT: CE sell signal (CURRENTLY DISABLED - LONG ONLY)
                elif self.sell_signal and ml_approved:
                    print(f"⚠️  SHORT signal detected but SHORT trading is currently disabled")
                    # SHORT trading not implemented yet
                    # When implemented, will need to:
                    # 1. Calculate contract_size_str for short
                    # 2. Place short order with Roostoo
                    # 3. Set TP/SL for short (inverse of long)
                elif (self.buy_signal or self.sell_signal) and not ml_approved:
                    print(f"❌ CE Signal REJECTED by ML Filter")
                    if ml_prediction:
                        print(f"   ML Class: {ml_prediction['predicted_class']} | Conf: {ml_prediction['confidence']*100:.1f}% | Threshold: {ML_CONFIDENCE_THRESHOLD*100:.1f}%")

        # LIVE P&L LOGGING
        if self.has_order:
            current_pl_pct = ((current_price - self.entry_price) / self.entry_price) * (1 if self.position_size > 0 else -1) * 100
            side = "LONG" if self.position_size > 0 else "SHORT"
            trend = "UP" if self.is_uptrend else "DOWN"
            print(f"→ {side} | Entry: {self.entry_price:.2f} | Now: {current_price:.2f} | P&L: {current_pl_pct:+.2f}% | ST: {trend}")

        print(f"Entry price: {self.entry_price:.2f}")

    # ========== REAL-TIME TP/SL MONITORING ==========
    # ADD THESE METHODS AT THE END OF THE CLASS

    def _start_tp_sl_monitoring(self):
        """Start real-time TP/SL monitoring thread (every 2 seconds)"""
        if not TP_SL_ENABLED:
            return
        
        self.stop_monitoring = False
        self.monitoring_thread = threading.Thread(target=self._monitor_tp_sl_realtime)
        self.monitoring_thread.daemon = True
        self.monitoring_thread.start()
        print(f"✅ Real-time TP/SL monitoring started (checking every {TP_SL_CHECK_INTERVAL}s)")

    def _stop_tp_sl_monitoring(self):
        """Stop real-time TP/SL monitoring thread"""
        self.stop_monitoring = True
        if self.monitoring_thread:
            self.monitoring_thread.join(timeout=5)
            print("⏹️  Real-time TP/SL monitoring stopped")

    def _monitor_tp_sl_realtime(self):
        """Monitor TP/SL every 2 seconds with LADDER limit order system"""
        while not self.stop_monitoring and self.has_order:
            try:
                # Get REAL-TIME price from Binance (faster than Roostoo)
                current_price = get_binance_current_price("ETHUSDT")

                if current_price <= 0:
                    time.sleep(TP_SL_CHECK_INTERVAL)
                    continue

                side = "LONG" if self.position_size > 0 else "SHORT"
                current_pl_pct = ((current_price - self.entry_price) / self.entry_price) * \
                                (1 if self.position_size > 0 else -1) * 100
                
                # Get current position to check if ladder orders filled
                current_pos_size, _ = get_roostoo_position(pair=self.symbol)

                # ===== LADDER TP LOGIC =====
                if TP_SL_ENABLED and self.tp_ladder_levels and self.original_position_size > 0:
                    # Calculate position size per level (equal distribution)
                    position_per_level = self.original_position_size / len(self.tp_ladder_levels)
                    
                    # Check each TP level
                    for i, tp_level_pct in enumerate(self.tp_ladder_levels):
                        tp_price_level = self.entry_price * (1 + tp_level_pct)
                        
                        # Skip if we already placed an order for this level (whether filled or not)
                        if tp_level_pct in self.tp_ladder_orders:
                            continue  # Already processed this level
                        
                        # No order yet - check if price reached this level
                        if side == "LONG" and current_price >= tp_price_level:
                            print(f"📊 TP Level {i+1} reached @ ${current_price:.2f} (Target: +{tp_level_pct*100:.0f}%)")
                            
                            if LIMIT_ORDER_AT_TP:
                                # Place LIMIT order at this TP level
                                order_id = place_roostoo_order(
                                    pair=self.symbol,
                                    side="SELL",  # Exit long
                                    order_type="LIMIT",
                                    quantity=str(position_per_level),
                                    price=tp_price_level
                                )
                                
                                if order_id:
                                    # Track this order
                                    self.tp_ladder_orders[tp_level_pct] = {
                                        'order_id': order_id,
                                        'placed_at': current_price,
                                        'size': position_per_level,
                                        'filled': False
                                    }
                                    self.current_tp_level = max(self.current_tp_level, i+1)
                                    print(f"✅ Ladder LIMIT order placed at Level {i+1}: ${tp_price_level:.2f} | ID={order_id} | Size={position_per_level:.4f}")
                                    
                                    # Send notification
                                    tp_message = (
                                        f"📋  <b>LADDER TP ORDER PLACED</b>\n"
                                        f"├─ Symbol: {self.symbol}\n"
                                        f"├─ Level: {i+1}/{len(self.tp_ladder_levels)}\n"
                                        f"├─ TP Price: ${tp_price_level:.2f} (+{tp_level_pct*100:.0f}%)\n"
                                        f"├─ Current Price: ${current_price:.2f}\n"
                                        f"├─ P&L: {current_pl_pct:+.2f}%\n"
                                        f"├─ Size: {position_per_level:.4f} contracts\n"
                                        f"├─ Order ID: {order_id}\n"
                                        f"└─ Waiting for price to reverse and fill...\n"
                                    )
                                    send_telegram_message(tp_message)
                                else:
                                    # Order failed, but mark as attempted to prevent spam
                                    self.tp_ladder_orders[tp_level_pct] = {
                                        'order_id': None,
                                        'placed_at': current_price,
                                        'size': position_per_level,
                                        'filled': False,
                                        'failed': True
                                    }
                                    print(f"❌ Ladder order at Level {i+1} failed to place")

                # CHECK STOP LOSS
                if TP_SL_ENABLED and self.sl_price:
                    sl_triggered = False

                    if side == "LONG" and current_price <= self.sl_price:
                        sl_triggered = True
                    elif side == "SHORT" and current_price >= self.sl_price:
                        sl_triggered = True

                    if sl_triggered:
                        print(f"🛑 SL triggered @ ${current_price:.2f}")

                        # CANCEL ALL PENDING TP LADDER ORDERS
                        for level_pct, order_info in list(self.tp_ladder_orders.items()):
                            if not order_info['filled']:
                                order_id = order_info['order_id']
                                print(f"❌ Canceling pending TP ladder order: {order_id}")
                                cancel_roostoo_order(order_id=order_id)
                        self.tp_ladder_orders.clear()

                        # CLOSE REMAINING POSITION AT MARKET
                        self._close_position("Stop Loss Hit")
                        send_sl_triggered_message(
                            symbol=self.symbol,
                            entry_price=self.entry_price,
                            exit_price=current_price,
                            pl_pct=current_pl_pct,
                            predicted_class=self.predicted_class_on_entry or 1
                        )
                        break
                
                time.sleep(TP_SL_CHECK_INTERVAL)
                
            except Exception as e:
                print(f"❌ Error in TP/SL monitoring: {e}")
                time.sleep(TP_SL_CHECK_INTERVAL)

    def _close_position(self, reason):
        """Close position and send notification"""
        current_price = get_roostoo_current_price(pair=self.symbol)
        final_pl_pct = ((current_price - self.entry_price) / self.entry_price) * \
                    (1 if self.position_size > 0 else -1) * 100

        close_roostoo_position(pair=self.symbol)

        # ✅ RECORD TRADE EXIT TO DATABASE
        try:
            from core.trading_history import history_db
            # Get the most recent open trade for this symbol and update it
            import sqlite3
            db_path = history_db.db_path
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE trades
                    SET exit_time = ?, exit_price = ?, pnl_pct = ?, reason = ?
                    WHERE symbol = ? AND exit_time IS NULL
                    ORDER BY entry_time DESC
                    LIMIT 1
                """, (
                    datetime.now(timezone.utc),
                    current_price,
                    final_pl_pct,
                    reason,
                    self.symbol
                ))
                conn.commit()
            print(f"📝 Trade exit recorded to database")
        except Exception as e:
            print(f"⚠️  Failed to record trade exit: {e}")

        self.position_size = 0
        self.has_order = False
        self.long_stop_prev = None
        self.short_stop_prev = None
        self.dir = 0
        self.prev_dir = 0
        self.tp_price = None
        self.sl_price = None
        self.predicted_class_on_entry = None
        self.tp_limit_placed = False
        self.tp_ladder_levels = []
        self.tp_ladder_orders = {}
        self.current_tp_level = 0
        self.original_position_size = 0

        # STOP MONITORING THREAD
        self._stop_tp_sl_monitoring()

        close_message = (
            f"🚨  <b>CLOSED POSITION</b>\n"
            f"├─ Symbol: {self.symbol}\n"
            f"├─ Reason: {reason}\n"
            f"├─ Exit Price: ${current_price:.2f}\n"
            f"├─ Entry Price: ${self.entry_price:.2f}\n"
            f"├─ P&L: {final_pl_pct:+.2f}%\n"
            f"└─ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        )
        print(f"CLOSED → {reason} @ {current_price:.2f} | P&L: {final_pl_pct:+.2f}%")
        send_telegram_message(close_message)

    def _format_entry_message(self, current_price, contract_size_str, entry_value, 
                            ml_prediction, side):
        """Format entry Telegram message with all probabilities"""
        emoji = "🚀" if side == "LONG" else "🔻"
        
        message = (
            f"{emoji}  <b>{side} POSITION OPENED</b>\n"
            f"├─ Symbol: {self.symbol}\n"
            f"├─ Entry Price: ${current_price:.2f}\n"
            f"├─ Size: {contract_size_str}\n"
            f"├─ Value: ${entry_value:.2f}\n"
            f"├─ CE Direction: {self.dir}\n"
            f"├─ Supertrend: {'UPTREND' if self.is_uptrend else 'DOWNTREND'}\n"
        )
        
        if ml_prediction:
            probs = ml_prediction['probabilities']
            tp_pct = TAKE_PROFIT_PCT.get(ml_prediction['predicted_class'], 0.01)
            sl_pct = STOP_LOSS_PCT.get(ml_prediction['predicted_class'], 0.015)

            message += (
                f"├─ ML Class: {ml_prediction['predicted_class']}\n"
                f"├─ ML Confidence: {ml_prediction['confidence']*100:.1f}%\n"
                f"├─ All Class Probabilities:\n"
                f"│   ├─ Class 0: {probs[0]*100:.2f}%\n"
                f"│   ├─ Class 1: {probs[1]*100:.2f}%\n"
                f"│   ├─ Class 2: {probs[2]*100:.2f}%\n"
                f"│   └─ Class 3: {probs[3]*100:.2f}%\n"
                f"├─ TP/SL Settings:\n"
                f"│   ├─ Take Profit: ${self.tp_price:.2f} (+{tp_pct*100:.1f}%)\n"
                f"│   └─ Stop Loss: ${self.sl_price:.2f} (-{sl_pct*100:.1f}%)\n"
            )
        
        message += f"└─ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        return message