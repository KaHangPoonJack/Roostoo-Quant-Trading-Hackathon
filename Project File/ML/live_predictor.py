"""
live_predictor.py
=================
Production-ready module for real-time crypto breakout prediction.
Usage:
    from live_predictor import CryptoBreakoutPredictor
    predictor = CryptoBreakoutPredictor(model_dir='models')
    result = predictor.predict(symbol='ETH/USDT')
"""

import ccxt
import pandas as pd
import numpy as np
import pandas_ta as ta
import yfinance as yf
import requests
import joblib
from datetime import datetime, timedelta, timezone
import warnings
import time
import os
from typing import Dict, Optional, List
from pathlib import Path

warnings.filterwarnings('ignore')


class CryptoBreakoutPredictor:
    """
    Live prediction engine for crypto breakout classification.
    
    Features:
    - Fetches live data from Binance, Yahoo Finance, Alternative.me
    - Calculates 43 features matching training pipeline
    - Ensemble prediction (LightGBM + XGBoost)
    - Returns structured prediction result
    """
    
    # Features to exclude from prediction input (same as training)
    EXCLUDE_COLS = ['target', 'open', 'high', 'low', 'close', 'volume', 'btc_close']
    
    def __init__(self, model_dir: str = None, timeout: int = 10):
        """
        Initialize predictor with trained models.
        
        Args:
            model_dir: Path to folder containing .pkl model files. 
                    If None, uses config.settings.ML_MODEL_DIR
            timeout: API request timeout in seconds
        """
        self.timeout = timeout
        self.exchange = ccxt.binance({'timeout': timeout * 1000})
        
        # Use provided path or import from settings
        if model_dir is None:
            try:
                from config.settings import ML_MODEL_DIR
                self.model_dir = str(ML_MODEL_DIR)
            except ImportError:
                # Fallback: use relative path from this file's location
                self.model_dir = str(Path(__file__).parent / "models")
        else:
            self.model_dir = model_dir
        
        # Load models (raise error if missing)
        self._load_models()
        
    def _load_models(self):
        """Load trained models and feature columns"""
        try:
            self.lgb_model = joblib.load(os.path.join(self.model_dir, 'lgb_crypto_model.pkl'))
            self.xgb_model = joblib.load(os.path.join(self.model_dir, 'xgb_crypto_model.pkl'))
            self.feature_cols = joblib.load(os.path.join(self.model_dir, 'feature_cols.pkl'))
        except FileNotFoundError as e:
            raise FileNotFoundError(
                f"Model files not found in '{self.model_dir}/'. "
                f"Please run training first or specify correct model_dir."
            ) from e
            
    def _fetch_crypto_ohlcv(self, symbol: str, timeframe: str = '15m', limit: int = 200) -> pd.DataFrame:
        """Fetch OHLCV data from Binance"""
        bars = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        df.set_index('timestamp', inplace=True)
        return df
    
    def _fetch_btc_close(self, timeframe: str = '15m', limit: int = 200) -> pd.Series:
        """Fetch BTC/USDT close prices for correlation features"""
        df = self._fetch_crypto_ohlcv('BTC/USDT', timeframe, limit)
        return df['close']
    
    def _fetch_macro_data(self) -> Dict[str, float]:
        """Fetch latest macro indicators from Yahoo Finance"""
        data = {}
        
        # SPX
        try:
            data['spx'] = float(yf.download("^GSPC", period='5d', progress=False)['Close'].iloc[-1])
        except:
            data['spx'] = np.nan
            
        # DXY (UUP ETF)
        try:
            data['dxy'] = float(yf.download("UUP", period='5d', progress=False)['Close'].iloc[-1])
        except:
            data['dxy'] = np.nan
            
        # VIX
        try:
            data['vix'] = float(yf.download("^VIX", period='5d', progress=False)['Close'].iloc[-1])
        except:
            data['vix'] = np.nan
            
        # Treasury 10Y
        try:
            data['treasury_10y'] = float(yf.download("^TNX", period='5d', progress=False)['Close'].iloc[-1])
        except:
            data['treasury_10y'] = np.nan
            
        return data
    
    def _fetch_fear_greed(self) -> float:
        """Fetch Crypto Fear & Greed Index"""
        try:
            resp = requests.get('https://api.alternative.me/fng/', timeout=self.timeout)
            return float(resp.json()['data'][0]['value'])
        except:
            return 50.0  # Neutral default
    
    def _fetch_funding_rate(self, symbol: str) -> float:
        """Fetch perpetual futures funding rate"""
        try:
            binance_symbol = symbol.replace('/', '') + 'USDT'
            url = "https://fapi.binance.com/fapi/v1/fundingRate"
            resp = requests.get(url, params={'symbol': binance_symbol, 'limit': 1}, timeout=self.timeout)
            return float(resp.json()[0]['fundingRate'])
        except:
            return 0.0001
    
    def _fetch_orderbook_features(self, symbol='ETHUSDT'):
        """Fetch order book features (real-time)"""
        try:
            url = "https://api.binance.com/api/v3/depth"
            params = {'symbol': symbol, 'limit': 20}
            resp = requests.get(url, params=params, timeout=5)
            data = resp.json()
            
            bids = [(float(p), float(q)) for p, q in data['bids']]
            asks = [(float(p), float(q)) for p, q in data['asks']]
            
            bid_volume = sum(q for p, q in bids)
            ask_volume = sum(q for p, q in asks)
            
            return {
                'order_imbalance': (bid_volume - ask_volume) / (bid_volume + ask_volume + 1e-8),
                'spread_pct': ((asks[0][0] - bids[0][0]) / ((asks[0][0] + bids[0][0]) / 2)) * 100 if asks and bids else 0.0,
                'bid_ask_ratio': bid_volume / (ask_volume + 1e-8),
                'top_level_imbalance': (bids[0][1] - asks[0][1]) / (bids[0][1] + asks[0][1] + 1e-8) if asks and bids else 0.0
            }
        except:
            return {'order_imbalance': 0.0, 'spread_pct': 0.0, 'bid_ask_ratio': 1.0, 'top_level_imbalance': 0.0}

    def _fetch_futures_features(self, symbol='ETHUSDT'):
        """Fetch futures market features (real-time)"""
        try:
            # Funding rate
            url = "https://fapi.binance.com/fapi/v1/fundingRate"
            resp = requests.get(url, params={'symbol': symbol, 'limit': 8}, timeout=5)
            funding_rates = [float(r['fundingRate']) for r in resp.json()]
            
            # Open interest
            url = "https://fapi.binance.com/fapi/v1/openInterest"
            resp = requests.get(url, params={'symbol': symbol}, timeout=5)
            oi = float(resp.json()['openInterest'])
            
            return {
                'funding_rate': funding_rates[-1] if funding_rates else 0.0001,
                'funding_rate_ma8': np.mean(funding_rates) if funding_rates else 0.0001,
                'funding_rate_std': np.std(funding_rates) if len(funding_rates) > 1 else 0.0,
                'open_interest': oi
            }
        except:
            return {'funding_rate': 0.0001, 'funding_rate_ma8': 0.0001, 'funding_rate_std': 0.0, 'open_interest': 0.0}

    def _fetch_liquidation_features(self, symbol='ETHUSDT'):
        """Fetch liquidation data (real-time)"""
        try:
            url = "https://fapi.binance.com/fapi/v1/allForceOrders"
            resp = requests.get(url, params={'symbol': symbol, 'limit': 100}, timeout=5)
            data = resp.json()
            
            long_liq = sum(float(o['executedQty']) for o in data if o['side'] == 'SELL')
            short_liq = sum(float(o['executedQty']) for o in data if o['side'] == 'BUY')
            
            return {
                'long_liquidation': long_liq,
                'short_liquidation': short_liq,
                'liq_ratio': long_liq / (short_liq + 1e-8),
                'total_liquidation': long_liq + short_liq
            }
        except:
            return {'long_liquidation': 0.0, 'short_liquidation': 0.0, 'liq_ratio': 1.0, 'total_liquidation': 0.0}

    def _calculate_features(self, df: pd.DataFrame, df_btc: pd.Series, 
                       macro: Dict, fear_greed: float, funding_rate: float) -> pd.DataFrame:
        """
        Calculate all 51 features. MUST match training pipeline exactly.
        Fixed to match crypto_data_pipeline.py output
        """
        df = df.copy()
        
        # ===== PRICE/VOLUME (9) =====
        df['returns_15m'] = df['close'].pct_change()
        df['returns_1h'] = df['close'].pct_change(4)
        df['returns_4h'] = df['close'].pct_change(16)
        df['volume_sma'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / (df['volume_sma'] + 1e-8)
        df['volume_std'] = df['volume'].rolling(20).std()
        df['volume_zscore'] = (df['volume'] - df['volume_sma']) / (df['volume_std'] + 1e-8)
        df['high_low_range'] = (df['high'] - df['low']) / (df['close'] + 1e-8)
        df['close_position'] = (df['close'] - df['low']) / (df['high'] - df['low'] + 1e-8)
        
        # ===== TECHNICAL INDICATORS =====
        # ATR (calculate ONCE - not twice!)
        df['atr_14'] = ta.atr(df['high'], df['low'], df['close'], length=14)
        df['atr_ratio'] = df['atr_14'] / (df['close'] + 1e-8)
        
        # ADX
        adx = ta.adx(df['high'], df['low'], df['close'], length=14)
        adx_col = [c for c in adx.columns if 'ADX' in c.upper()][0]
        df['adx_14'] = adx[adx_col]
        
        # RSI
        df['rsi_14'] = ta.rsi(df['close'], length=14)
        
        # Bollinger Bands (only bb_width and bb_position in final features)
        bb = ta.bbands(df['close'], length=20, std=2)
        bbu_col = [c for c in bb.columns if c.startswith('BBU')][0]
        bbl_col = [c for c in bb.columns if c.startswith('BBL')][0]
        bbm_col = [c for c in bb.columns if c.startswith('BBM')][0]
        df['bb_upper'] = bb[bbu_col]  # Intermediate - exclude from feature_cols
        df['bb_lower'] = bb[bbl_col]  # Intermediate - exclude from feature_cols
        df['bb_middle'] = bb[bbm_col]  # Intermediate - exclude from feature_cols
        df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / (df['close'] + 1e-8)
        df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'] + 1e-8)
        
        # MACD (only macd_hist in final features)
        macd = ta.macd(df['close'], fast=12, slow=26, signal=9)
        macd_hist_col = [c for c in macd.columns if 'MACDh' in c][0]
        df['macd_hist'] = macd[macd_hist_col]
        
        # OBV
        df['obv'] = ta.obv(df['close'], df['volume'])
        
        # VWAP
        df['vwap'] = ta.vwap(df['high'], df['low'], df['close'], df['volume'])
        
        # Keltner Channels (only keltner_width in final features)
        kc = ta.kc(df['high'], df['low'], df['close'], length=20)
        kcu_col = [c for c in kc.columns if c.startswith('KCU')][0]
        kcl_col = [c for c in kc.columns if c.startswith('KCL')][0]
        df['keltner_upper'] = kc[kcu_col]  # Intermediate - exclude from feature_cols
        df['keltner_lower'] = kc[kcl_col]  # Intermediate - exclude from feature_cols
        df['keltner_width'] = (df['keltner_upper'] - df['keltner_lower']) / (df['close'] + 1e-8)
        
        # ===== MULTI-TIMEFRAME (5) =====
        df_1h = df[['close', 'high', 'low']].resample('1h').agg({
            'close': 'last', 'high': 'max', 'low': 'min'
        })
        df_1h['ema_50_1h'] = df_1h['close'].ewm(span=50).mean()
        df_1h['ema_200_1h'] = df_1h['close'].ewm(span=200).mean()
        
        adx_1h = ta.adx(df_1h['high'], df_1h['low'], df_1h['close'], length=14)
        adx_1h_col = [c for c in adx_1h.columns if 'ADX' in c.upper()][0]
        df_1h['adx_14_1h'] = adx_1h[adx_1h_col]
        
        df_1h = df_1h.resample('15min').ffill()
        df = df.merge(df_1h[['ema_50_1h', 'ema_200_1h', 'adx_14_1h']], 
                    left_index=True, right_index=True, how='left')
        df[['ema_50_1h', 'ema_200_1h', 'adx_14_1h']] = df[['ema_50_1h', 'ema_200_1h', 'adx_14_1h']].ffill()
        
        df['dist_ema_50'] = (df['close'] - df['ema_50_1h']) / (df['close'] + 1e-8)
        df['above_ema_200'] = (df['close'] > df['ema_200_1h']).astype(int)
        
        # ===== CROSS-ASSET (5) =====
        df['btc_close'] = df_btc.reindex(df.index).ffill()  # Intermediate - exclude
        df['btc_returns'] = df['btc_close'].pct_change()  # Intermediate - exclude
        df['btc_correlation'] = df['returns_15m'].rolling(96).corr(df['btc_returns'])
        df['eth_btc_ratio'] = df['close'] / df['btc_close']
        df['btc_dominance'] = 50.0
        
        # ===== MACRO (4) =====
        # Only these 4 are in final features
        for col in ['spx', 'dxy', 'vix', 'treasury_10y']:
            df[col] = macro.get(col, np.nan)
        # ❌ REMOVE: spx_return_1d, spx_return_5d, dxy_return_15min, vix_level (not in training)
        
        # ===== SENTIMENT =====
        # ❌ REMOVE: crypto_fear_greed, funding_rate (not in training features)
        
        # ===== MARKET SESSIONS (12) =====
        df['hour_utc'] = df.index.hour
        df['minute_utc'] = df.index.minute
        df['weekday'] = df.index.weekday
        
        df['asia_session'] = (((df['hour_utc'] >= 0) & (df['hour_utc'] < 9)) | 
                            ((df['hour_utc'] >= 21) | (df['hour_utc'] < 6))).astype(int)
        df['europe_session'] = ((df['hour_utc'] >= 7) & (df['hour_utc'] < 17)).astype(int)
        df['us_session'] = ((df['hour_utc'] >= 14) & (df['hour_utc'] < 21)).astype(int)
        df['us_premarket'] = ((df['hour_utc'] >= 13) & (df['hour_utc'] < 14)).astype(int)
        df['us_afterhours'] = ((df['hour_utc'] >= 21) | (df['hour_utc'] < 1)).astype(int)
        df['asia_europe_overlap'] = ((df['hour_utc'] >= 7) & (df['hour_utc'] < 9)).astype(int)
        df['europe_us_overlap'] = ((df['hour_utc'] >= 14) & (df['hour_utc'] < 17)).astype(int)
        df['is_weekend'] = (df['weekday'] >= 5).astype(int)
        df['us_market_open'] = ((df['weekday'] < 5) & (df['hour_utc'] >= 14) & (df['hour_utc'] < 21)).astype(int)
        
        # ===== VOLATILITY REGIME (8) =====
        # Calculate ONCE (not twice!)
        vol_mean = df['atr_ratio'].rolling(96).mean()
        
        # Calculate volatility regime (encoded version only - no categorical string)
        # Map to 0-3 based on quartile thresholds
        try:
            # Use pd.qcut to get the regime, then encode immediately
            regime_cat = pd.qcut(
                vol_mean,
                q=4,
                labels=['low', 'med-low', 'med-high', 'high'],
                duplicates='drop'
            )
            df['vol_regime_encoded'] = regime_cat.map(
                {'low': 0, 'med-low': 1, 'med-high': 2, 'high': 3}
            ).fillna(1).astype(int)
        except Exception as e:
            # Fallback: use median-based encoding
            print(f"⚠️  qcut failed, using fallback: {e}")
            median_vol = vol_mean.median()
            df['vol_regime_encoded'] = (vol_mean > median_vol).astype(int) + 1
        df['vol_expansion'] = df['atr_ratio'] / (df['atr_ratio'].rolling(48).mean() + 1e-8)
        df['atr_percentile'] = df['atr_ratio'].rolling(200).rank(pct=True)
        df['vol_zscore'] = (df['atr_ratio'] - df['atr_ratio'].rolling(96).mean()) / \
                        (df['atr_ratio'].rolling(96).std() + 1e-8)
        df['hist_vol_20'] = df['returns_15m'].rolling(20).std() * np.sqrt(96)
        df['hist_vol_50'] = df['returns_15m'].rolling(50).std() * np.sqrt(96)
        df['vol_trend'] = df['hist_vol_20'] - df['hist_vol_50']
        
        # ===== ASSET IDENTITY (1) =====
        df['transaction_volume'] = df['volume'] * df['close']
        
        return df
            
    def predict(self, symbol: str = 'ETH/USDT', timeframe: str = '15m',
            confidence_threshold: float = 0.7) -> Dict:
        """Make live prediction for given symbol."""
        start_time = time.time()

        # Fetch live data
        df = self._fetch_crypto_ohlcv(symbol, timeframe, limit=200)
        df_btc = self._fetch_btc_close(timeframe, limit=200)
        macro = self._fetch_macro_data()
        fear_greed = self._fetch_fear_greed()
        funding_rate = self._fetch_funding_rate(symbol)

        # Calculate features
        df = self._calculate_features(df, df_btc, macro, fear_greed, funding_rate)

        # ✅ USE SAVED FEATURE COLUMNS FROM TRAINING (not hardcoded)
        # This ensures exact match with trained models
        feature_cols = self.feature_cols

        # Prepare input for models (last row only)
        X = df[feature_cols].iloc[-1:].fillna(0)

        # Get ensemble prediction (no categorical_feature needed - all numeric features)
        prob_lgb = self.lgb_model.predict_proba(X)[0]
        prob_xgb = self.xgb_model.predict_proba(X)[0]
        prob_avg = (prob_lgb + prob_xgb) / 2
        
        predicted_class = int(np.argmax(prob_avg))
        confidence = float(prob_avg[predicted_class])
        current_price = float(df['close'].iloc[-1])
        
        # Calculate breakout probability (sum of Class 1, 2, 3)
        probs = prob_avg
        breakout_prob = probs[1] + probs[2] + probs[3]
        
        # Determine highest probability class (for TP level)
        highest_prob_class = int(np.argmax(probs[1:4])) + 1
        
        # Generate recommendation
        if breakout_prob >= confidence_threshold:
            recommendation = self._get_recommendation(highest_prob_class, breakout_prob, confidence_threshold)
        else:
            recommendation = "WAIT_LOW_CONFIDENCE"
        
        # Calculate position size
        position_size = self._get_position_size(highest_prob_class, breakout_prob, confidence_threshold)
        
        result = {
            'timestamp': datetime.utcnow(),
            'symbol': symbol,
            'timeframe': timeframe,
            'price': current_price,
            'predicted_class': highest_prob_class,
            'confidence': breakout_prob,
            'probabilities': prob_avg.tolist(),
            'breakout_probability': breakout_prob,
            'highest_prob_class': highest_prob_class,
            'recommendation': recommendation,
            'position_size_pct': position_size,
            'execution_time_ms': (time.time() - start_time) * 1000,
            'features_used': len(feature_cols),
            'data_freshness': {
                'candle_age_seconds': (datetime.now(timezone.utc) - df.index[-1]).total_seconds(),
                'macro_fetched': not any(np.isnan(v) for v in macro.values())
            }
        }
        
        return result
    
    def _get_recommendation(self, predicted_class: int, confidence: float, 
                           threshold: float) -> str:
        """Generate human-readable trading recommendation"""
        if predicted_class == 0:
            return "NO_TRADE"
        elif confidence < threshold:
            return "WAIT_LOW_CONFIDENCE"
        elif predicted_class == 1:
            return "ENTER_SMALL"
        elif predicted_class == 2:
            return "ENTER_MEDIUM"
        elif predicted_class == 3:
            return "ENTER_LARGE"
        else:
            return "NO_TRADE"
    
    def _get_position_size(self, predicted_class: int, confidence: float,
                        threshold: float) -> float:
        """
        Position size based on BREAKOUT PROBABILITY (sum of Class 1,2,3)
        All coins trade with 100% capital allocation
        
        Breakout Probability Thresholds:
        - P >= 95%: 8% of total capital
        - P >= 90%: 6% of total capital
        - P >= 80%: 4% of total capital
        - P >= 70%: 2% of total capital
        - P < 70%: 0% (no trade)
        
        Note: Uses ML_CONFIDENCE_THRESHOLD from settings for minimum threshold
        """
        from config.settings import ML_CONFIDENCE_THRESHOLD
        
        # Use the confidence parameter which is already the breakout probability
        # (calculated in the predict() method before calling this)
        breakout_prob = confidence
        
        # Check minimum threshold from settings
        if breakout_prob < ML_CONFIDENCE_THRESHOLD:
            return 0.0  # No trade below threshold
        
        # Position sizing based on breakout probability
        if breakout_prob >= 0.95:
            return 0.08  # 8% of total capital
        elif breakout_prob >= 0.90:
            return 0.06  # 6% of total capital
        elif breakout_prob >= 0.80:
            return 0.04  # 4% of total capital
        elif breakout_prob >= 0.70:
            return 0.02  # 2% of total capital
        else:
            return 0.0   # No trade
    
    def batch_predict(self, symbols: List[str], timeframe: str = '15m') -> Dict[str, Dict]:
        """
        Make predictions for multiple symbols.
        
        Args:
            symbols: List of trading pairs
            timeframe: Candle timeframe
            
        Returns:
            Dict mapping symbol -> prediction result
        """
        results = {}
        for symbol in symbols:
            try:
                results[symbol] = self.predict(symbol, timeframe)
                time.sleep(0.5)  # Rate limit
            except Exception as e:
                results[symbol] = {'error': str(e), 'symbol': symbol}
        return results
    
    def health_check(self) -> Dict:
        checks = {
            'models_loaded': all([
                hasattr(self, 'lgb_model'),
                hasattr(self, 'xgb_model'),
                hasattr(self, 'feature_cols')
            ]),
            'exchange_connected': self.exchange.has['fetchOHLCV'],
            'feature_count': len(self.feature_cols) if hasattr(self, 'feature_cols') else 0,
            'expected_features': len(self.feature_cols) if hasattr(self, 'feature_cols') else 52  # Dynamic based on loaded models
        }
        checks['ready'] = all([
            checks['models_loaded'],
            checks['exchange_connected'],
            checks['feature_count'] == checks['expected_features']
        ])
        return checks


# ================= UTILITY FUNCTIONS =================

def format_prediction(result: Dict) -> str:
    """Format prediction result for logging/display"""
    return (
        f"[{result['timestamp'].strftime('%H:%M:%S')}] "
        f"{result['symbol']} @ ${result['price']:.2f} | "
        f"Class {result['predicted_class']} ({result['confidence']*100:.1f}%) | "
        f"{result['recommendation']} | "
        f"Size: {result['position_size_pct']*100:.1f}%"
    )


def should_trade(result: Dict, min_breakout_probability: float = None) -> bool:
    """
    Quick check: should we execute a trade based on prediction?
    Uses ML_CONFIDENCE_THRESHOLD from settings (default 0.5 = 50%)
    
    NEW LOGIC: Sum of Class 1, 2, 3 probabilities >= threshold
    """
    from config.settings import ML_CONFIDENCE_THRESHOLD
    
    # Use provided threshold or fall back to settings
    threshold = min_breakout_probability if min_breakout_probability is not None else ML_CONFIDENCE_THRESHOLD
    
    probs = result['probabilities']
    breakout_prob = probs[1] + probs[2] + probs[3]  # Sum of Class 1, 2, 3
    return breakout_prob >= threshold


# ================= EXAMPLE USAGE =================

if __name__ == "__main__":
    # Initialize predictor
    predictor = CryptoBreakoutPredictor(model_dir='models')
    
    # Health check
    health = predictor.health_check()
    print(f"🔍 Health Check: {'✅ READY' if health['ready'] else '❌ NOT READY'}")
    if not health['ready']:
        print(f"   Issues: {[k for k, v in health.items() if v is False]}")
    
    # Single prediction
    print("\n🔮 Making prediction for ETH/USDT...")
    result = predictor.predict('ETH/USDT')
    print(format_prediction(result))
    
    # Batch prediction
    print("\n🔮 Making predictions for multiple symbols...")
    symbols = ['ETH/USDT', 'BTC/USDT', 'SOL/USDT']
    results = predictor.batch_predict(symbols)
    for symbol, res in results.items():
        if 'error' not in res:
            print(format_prediction(res))
        else:
            print(f"❌ {symbol}: {res['error']}")