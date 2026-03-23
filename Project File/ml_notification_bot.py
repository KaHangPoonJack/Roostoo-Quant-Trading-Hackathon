"""
ml_notification_bot.py
======================
Monitoring bot for CE trading signals WITHOUT actual trading
- Tracks CE signal generation
- Records ML predictions
- Web dashboard for monitoring
- No actual trades executed
"""

import numpy as np
import pandas as pd
import time
from datetime import datetime, timezone
from flask import Flask, render_template_string, jsonify
from flask_cors import CORS
import threading
import signal
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import ML_MODEL_DIR, ML_ENABLED, ML_CONFIDENCE_THRESHOLD
from ML.live_predictor import CryptoBreakoutPredictor, should_trade
from strategies.chandelier_exit import ChandelierExit
from data.fetcher import load_binance_historical_data, get_latest_binance_candle
from core.binance_client import get_binance_current_price
from core.utils import wait_until_next_quarter_hour

# Flask app for monitoring dashboard
app = Flask(__name__)
CORS(app)

# Global state for monitoring
monitoring_state = {
    'signals': [],  # CE signals generated
    'ml_predictions': [],  # ML predictions
    'coins': {},  # Per-coin monitoring data
    'start_time': datetime.now(timezone.utc),
    'is_running': False
}


class CoinMonitor:
    """Monitor CE signals and ML predictions for a single coin without trading"""
    
    def __init__(self, symbol, binance_symbol, model_dir):
        self.symbol = symbol
        self.binance_symbol = binance_symbol
        self.model_dir = model_dir
        
        # Initialize ML predictor
        self.ml_predictor = CryptoBreakoutPredictor(model_dir=model_dir) if ML_ENABLED else None
        
        # Load historical data
        self.df = self._load_historical_data()
        
        # Initialize CE strategy (no trading)
        self.strategy = ChandelierExit(self.df)
        self.strategy.symbol = f"{symbol}/USD"
        
        # Monitoring stats
        self.ce_signals_count = 0
        self.ml_approved_count = 0
        self.last_signal_time = None
        self.last_ml_time = None
        
        print(f"✅ {symbol}: Monitor initialized")
    
    def _load_historical_data(self, days_back=3, interval='15m'):
        """Load historical candles"""
        return load_binance_historical_data(
            symbol=self.binance_symbol,
            interval=interval,
            days_back=days_back
        )
    
    def run_monitoring_cycle(self):
        """Run one monitoring cycle (every 15min candle)"""
        try:
            # Fetch latest candle
            latest_df = get_latest_binance_candle(
                symbol=self.binance_symbol,
                interval='15m'
            )
            
            if latest_df.empty:
                return
            
            # Update dataframe
            self.df = pd.concat([self.df, latest_df])
            self.strategy.df = self.df
            
            # Get current price
            current_price = get_binance_current_price(self.binance_symbol)
            self.strategy.current_price = current_price
            
            # Execute CE strategy (no trading, just signal generation)
            self.strategy.next()
            
            # Get ML prediction
            ml_prediction = None
            if self.ml_predictor:
                try:
                    ccxt_symbol = f"{self.symbol}/USDT"
                    ml_prediction = self.ml_predictor.predict(ccxt_symbol, timeframe='15m')
                    
                    # Record ML prediction
                    self._record_ml_prediction(ml_prediction)
                except Exception as e:
                    print(f"⚠️  {self.symbol}: ML prediction failed: {e}")
            
            # Check for CE signal
            if self.strategy.buy_signal or self.strategy.sell_signal:
                self.ce_signals_count += 1
                self.last_signal_time = datetime.now(timezone.utc)
                
                # Check if ML approves
                ml_approved = False
                if ml_prediction:
                    ml_approved = should_trade(ml_prediction, min_breakout_probability=ML_CONFIDENCE_THRESHOLD)
                    if ml_approved:
                        self.ml_approved_count += 1
                
                # Record signal
                self._record_ce_signal(
                    signal_type='BUY' if self.strategy.buy_signal else 'SELL',
                    ml_approved=ml_approved,
                    ml_prediction=ml_prediction
                )
                
                print(f"🚨 {self.symbol}: CE {self.strategy.buy_signal and 'BUY' or 'SELL'} Signal | ML Approved: {ml_approved}")
            
            # Update monitoring state
            monitoring_state['coins'][self.symbol] = {
                'ce_signals': self.ce_signals_count,
                'ml_approved': self.ml_approved_count,
                'last_signal': self.last_signal_time.isoformat() if self.last_signal_time else None,
                'last_ml': self.last_ml_time.isoformat() if self.last_ml_time else None,
                'current_price': current_price,
                'ce_direction': self.strategy.dir,
                'supertrend': 'UPTREND' if self.strategy.is_uptrend else 'DOWNTREND'
            }
            
        except Exception as e:
            print(f"❌ {self.symbol}: Monitoring error: {e}")
    
    def _record_ce_signal(self, signal_type, ml_approved, ml_prediction=None):
        """Record CE signal to monitoring state"""
        signal_data = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'symbol': self.symbol,
            'type': signal_type,
            'ml_approved': ml_approved,
            'price': self.strategy.current_price,
            'ce_direction': self.strategy.dir,
            'supertrend': 'UPTREND' if self.strategy.is_uptrend else 'DOWNTREND'
        }
        
        if ml_prediction:
            signal_data['ml_class'] = ml_prediction.get('predicted_class')
            signal_data['ml_confidence'] = ml_prediction.get('confidence')
            signal_data['breakout_prob'] = ml_prediction.get('breakout_probability')
        
        monitoring_state['signals'].append(signal_data)
        
        # Keep only last 100 signals
        if len(monitoring_state['signals']) > 100:
            monitoring_state['signals'] = monitoring_state['signals'][-100:]
    
    def _record_ml_prediction(self, ml_prediction):
        """Record ML prediction to monitoring state"""
        self.last_ml_time = datetime.now(timezone.utc)
        
        prediction_data = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'symbol': self.symbol,
            'predicted_class': ml_prediction.get('predicted_class'),
            'confidence': ml_prediction.get('confidence'),
            'breakout_prob': ml_prediction.get('breakout_probability'),
            'recommendation': ml_prediction.get('recommendation'),
            'probabilities': ml_prediction.get('probabilities')
        }
        
        monitoring_state['ml_predictions'].append(prediction_data)
        
        # Keep only last 200 predictions
        if len(monitoring_state['ml_predictions']) > 200:
            monitoring_state['ml_predictions'] = monitoring_state['ml_predictions'][-200:]


# Coin monitors
monitors = {}


def run_monitoring():
    """Run monitoring loop for all coins"""
    coins_config = [
        {'symbol': 'BTC', 'binance_symbol': 'BTCUSDT', 'model_dir': str(ML_MODEL_DIR / 'btc_models')},
        {'symbol': 'ETH', 'binance_symbol': 'ETHUSDT', 'model_dir': str(ML_MODEL_DIR / 'eth_models')},
        {'symbol': 'DOGE', 'binance_symbol': 'DOGEUSDT', 'model_dir': str(ML_MODEL_DIR / 'doge_models')},
        {'symbol': 'SOL', 'binance_symbol': 'SOLUSDT', 'model_dir': str(ML_MODEL_DIR / 'sol_models')},
        {'symbol': 'PEPE', 'binance_symbol': 'PEPEUSDT', 'model_dir': str(ML_MODEL_DIR / 'pepe_models')}
    ]
    
    # Initialize monitors
    for coin in coins_config:
        monitors[coin['symbol']] = CoinMonitor(
            symbol=coin['symbol'],
            binance_symbol=coin['binance_symbol'],
            model_dir=coin['model_dir']
        )
    
    monitoring_state['is_running'] = True
    print("\n" + "="*70)
    print("🔍 CE SIGNAL MONITORING STARTED")
    print("="*70)
    print(f"📊 Monitoring {len(monitors)} coins")
    print(f"🤖 ML Enabled: {ML_ENABLED}")
    print(f"📈 Threshold: {ML_CONFIDENCE_THRESHOLD*100:.0f}%")
    print("="*70 + "\n")
    
    # Monitoring loop
    while monitoring_state['is_running']:
        try:
            # Wait for next 15min candle
            wait_until_next_quarter_hour()
            time.sleep(3)
            
            # Run monitoring cycle for all coins
            for symbol, monitor in monitors.items():
                monitor.run_monitoring_cycle()
            
        except KeyboardInterrupt:
            print("\n⚠️  Monitoring stopped by user")
            break
        except Exception as e:
            print(f"❌ Monitoring loop error: {e}")
            time.sleep(60)
    
    monitoring_state['is_running'] = False


# Flask Routes for Dashboard

@app.route('/')
def dashboard():
    """Monitoring dashboard HTML"""
    return render_template_string(DASHBOARD_HTML)


@app.route('/api/status')
def get_status():
    """Get monitoring status"""
    return jsonify({
        'is_running': monitoring_state['is_running'],
        'start_time': monitoring_state['start_time'].isoformat(),
        'uptime_seconds': (datetime.now(timezone.utc) - monitoring_state['start_time']).total_seconds(),
        'coins_monitored': len(monitors),
        'total_signals': len(monitoring_state['signals']),
        'total_predictions': len(monitoring_state['ml_predictions']),
        'timestamp': datetime.now(timezone.utc).isoformat()
    })


@app.route('/api/signals')
def get_signals():
    """Get CE signals"""
    return jsonify({
        'signals': monitoring_state['signals'][-50:],  # Last 50 signals
        'timestamp': datetime.now(timezone.utc).isoformat()
    })


@app.route('/api/ml-predictions')
def get_ml_predictions():
    """Get ML predictions"""
    return jsonify({
        'predictions': monitoring_state['ml_predictions'][-50:],  # Last 50 predictions
        'timestamp': datetime.now(timezone.utc).isoformat()
    })


@app.route('/api/coins')
def get_coins():
    """Get per-coin monitoring data"""
    return jsonify({
        'coins': monitoring_state['coins'],
        'timestamp': datetime.now(timezone.utc).isoformat()
    })


# Dashboard HTML Template
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CE Signal Monitor</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #020617, #0f172a, #1e293b);
            color: #e2e8f0;
            min-height: 100vh;
            padding: 20px;
        }
        .container { max-width: 1400px; margin: 0 auto; }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 30px;
            padding: 20px;
            background: rgba(30, 41, 59, 0.8);
            border-radius: 12px;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
        }
        .header h1 { color: #3b82f6; }
        .status-indicator {
            display: inline-block;
            width: 12px;
            height: 12px;
            border-radius: 50%;
            margin-right: 8px;
        }
        .status-indicator.active { background: #10b981; }
        .status-indicator.inactive { background: #ef4444; }
        .card {
            background: rgba(30, 41, 59, 0.8);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.3);
        }
        .card h2 { margin-bottom: 15px; color: #3b82f6; }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
        }
        .stat {
            background: rgba(59, 130, 246, 0.1);
            padding: 15px;
            border-radius: 8px;
            text-align: center;
        }
        .stat-label { font-size: 0.9em; color: #94a3b8; margin-bottom: 5px; }
        .stat-value { font-size: 1.5em; font-weight: 700; color: #3b82f6; }
        .coin-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 15px;
        }
        .coin-card {
            background: rgba(59, 130, 246, 0.1);
            padding: 15px;
            border-radius: 8px;
            border: 1px solid rgba(59, 130, 246, 0.3);
        }
        .signal-list {
            max-height: 400px;
            overflow-y: auto;
        }
        .signal-item {
            background: rgba(15, 23, 42, 0.5);
            padding: 12px;
            margin-bottom: 10px;
            border-radius: 8px;
            border-left: 4px solid #3b82f6;
        }
        .signal-item.buy { border-left-color: #10b981; }
        .signal-item.sell { border-left-color: #ef4444; }
        .positive { color: #10b981; }
        .negative { color: #ef4444; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 10px; text-align: left; border-bottom: 1px solid #334155; }
        th { background: rgba(15, 23, 42, 0.5); color: #3b82f6; }
        tr:hover { background: rgba(59, 130, 246, 0.1); }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔍 CE Signal Monitor</h1>
            <div>
                <span id="status-indicator" class="status-indicator"></span>
                <span id="status-text">Loading...</span>
                <span id="current-time" style="margin-left: 20px;"></span>
            </div>
        </div>

        <div class="stats-grid">
            <div class="stat">
                <div class="stat-label">Total CE Signals</div>
                <div id="total-signals" class="stat-value">0</div>
            </div>
            <div class="stat">
                <div class="stat-label">ML Approved</div>
                <div id="ml-approved" class="stat-value">0</div>
            </div>
            <div class="stat">
                <div class="stat-label">Approval Rate</div>
                <div id="approval-rate" class="stat-value">0%</div>
            </div>
            <div class="stat">
                <div class="stat-label">Uptime</div>
                <div id="uptime" class="stat-value">0h</div>
            </div>
        </div>

        <div class="card" style="margin-top: 20px;">
            <h2>📊 Coins Status</h2>
            <div id="coins-container" class="coin-grid"></div>
        </div>

        <div class="card">
            <h2>🚨 Recent CE Signals</h2>
            <div id="signals-container" class="signal-list"></div>
        </div>

        <div class="card">
            <h2>🔮 Recent ML Predictions</h2>
            <table>
                <thead>
                    <tr>
                        <th>Time</th>
                        <th>Symbol</th>
                        <th>Class</th>
                        <th>Confidence</th>
                        <th>Breakout %</th>
                        <th>Recommendation</th>
                    </tr>
                </thead>
                <tbody id="ml-predictions-tbody"></tbody>
            </table>
        </div>
    </div>

    <script>
        function updateTime() {
            document.getElementById('current-time').textContent = new Date().toLocaleTimeString();
        }

        async function loadDashboard() {
            try {
                const [status, signals, coins] = await Promise.all([
                    fetch('/api/status').then(r => r.json()),
                    fetch('/api/signals').then(r => r.json()),
                    fetch('/api/coins').then(r => r.json())
                ]);

                // Update status
                const indicator = document.getElementById('status-indicator');
                const statusText = document.getElementById('status-text');
                if (status.is_running) {
                    indicator.className = 'status-indicator active';
                    statusText.textContent = 'Monitoring Active';
                } else {
                    indicator.className = 'status-indicator inactive';
                    statusText.textContent = 'Stopped';
                }

                // Update stats
                document.getElementById('total-signals').textContent = status.total_signals;
                
                const mlApproved = signals.signals.filter(s => s.ml_approved).length;
                document.getElementById('ml-approved').textContent = mlApproved;
                
                const approvalRate = status.total_signals > 0 ? (mlApproved / status.total_signals * 100) : 0;
                document.getElementById('approval-rate').textContent = approvalRate.toFixed(1) + '%';
                
                const uptimeHours = (status.uptime_seconds / 3600).toFixed(1);
                document.getElementById('uptime').textContent = uptimeHours + 'h';

                // Update coins
                const coinsContainer = document.getElementById('coins-container');
                coinsContainer.innerHTML = '';
                for (const [symbol, data] of Object.entries(coins.coins)) {
                    coinsContainer.innerHTML += `
                        <div class="coin-card">
                            <h3>🪙 ${symbol}</h3>
                            <p>CE Signals: <strong>${data.ce_signals}</strong></p>
                            <p>ML Approved: <strong>${data.ml_approved}</strong></p>
                            <p>Price: <strong>$${(data.current_price || 0).toFixed(2)}</strong></p>
                            <p>Supertrend: <strong class="${data.supertrend === 'UPTREND' ? 'positive' : 'negative'}">${data.supertrend}</strong></p>
                        </div>
                    `;
                }

                // Update signals
                const signalsContainer = document.getElementById('signals-container');
                signalsContainer.innerHTML = '';
                signals.signals.slice(-20).reverse().forEach(signal => {
                    const time = new Date(signal.timestamp).toLocaleTimeString();
                    signalsContainer.innerHTML += `
                        <div class="signal-item ${signal.type.toLowerCase()}">
                            <strong>${signal.symbol}</strong> - ${signal.type} Signal
                            <br><small>${time}</small>
                            <br>ML Approved: <strong class="${signal.ml_approved ? 'positive' : 'negative'}">${signal.ml_approved ? 'Yes' : 'No'}</strong>
                        </div>
                    `;
                });

                // Update ML predictions
                const tbody = document.getElementById('ml-predictions-tbody');
                tbody.innerHTML = '';
                signals.signals.slice(-20).reverse().forEach(signal => {
                    if (signal.ml_class !== undefined) {
                        const time = new Date(signal.timestamp).toLocaleTimeString();
                        tbody.innerHTML += `
                            <tr>
                                <td>${time}</td>
                                <td>${signal.symbol}</td>
                                <td>Class ${signal.ml_class}</td>
                                <td>${(signal.ml_confidence * 100 || 0).toFixed(1)}%</td>
                                <td>${(signal.breakout_prob * 100 || 0).toFixed(1)}%</td>
                                <td>${signal.ml_approved ? '<span class="positive">APPROVED</span>' : '<span class="negative">WAIT</span>'}</td>
                            </tr>
                        `;
                    }
                });

            } catch (error) {
                console.error('Error loading dashboard:', error);
            }
        }

        setInterval(updateTime, 1000);
        setInterval(loadDashboard, 5000);
        updateTime();
        loadDashboard();
    </script>
</body>
</html>
"""


# Signal handler for graceful shutdown
def signal_handler(sig, frame):
    print("\n⚠️  Shutdown signal received...")
    monitoring_state['is_running'] = False
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    
    # Start monitoring in background thread
    monitoring_thread = threading.Thread(target=run_monitoring, daemon=True)
    monitoring_thread.start()
    
    # Start Flask dashboard
    print("\n🌐 Starting monitoring dashboard...")
    print("📊 Dashboard: http://localhost:5001")
    print("="*70 + "\n")
    
    app.run(host='0.0.0.0', port=5001, debug=False, use_reloader=False)
