"""
api_server.py
=============
Flask API server for live trading dashboard
"""

from flask import Flask, jsonify, render_template
from flask_cors import CORS
from datetime import datetime, timezone
from typing import Dict
from core.trading_history import history_db
import json
import threading
import time

app = Flask(__name__, template_folder='../web', static_folder='../web/static')
CORS(app)

# Global state for real-time updates
live_state = {
    'traders': {},
    'last_updated': None,
    'bot_status': 'stopped'
}


@app.route('/api/status', methods=['GET'])
def get_status():
    """Get overall bot status"""
    return jsonify({
        'status': live_state['bot_status'],
        'last_updated': live_state['last_updated'],
        'timestamp': datetime.now(timezone.utc).isoformat()
    })


@app.route('/api/traders', methods=['GET'])
def get_traders():
    """Get status of all traders"""
    return jsonify({
        'traders': live_state['traders'],
        'timestamp': datetime.now(timezone.utc).isoformat()
    })


@app.route('/api/trader/<symbol>', methods=['GET'])
def get_trader(symbol):
    """Get status of specific trader"""
    if symbol not in live_state['traders']:
        return jsonify({'error': f'Trader {symbol} not found'}), 404
    
    trader_state = live_state['traders'][symbol]
    
    return jsonify({
        'symbol': symbol,
        'state': trader_state,
        'recent_trades': history_db.get_recent_trades(symbol, limit=10),
        'open_trades': history_db.get_open_trades(symbol),
        'stats': history_db.get_stats(symbol),
        'timestamp': datetime.now(timezone.utc).isoformat()
    })


@app.route('/api/metrics', methods=['GET'])
def get_metrics():
    """Get live metrics for all coins"""
    metrics = history_db.get_all_symbols_metrics()

    # Get stats for each symbol
    stats = {}
    for symbol in metrics.keys():
        stats[symbol] = history_db.get_stats(symbol)
    
    # Get latest ML predictions for each symbol
    ml_predictions = {}
    for symbol in metrics.keys():
        recent_preds = history_db.get_recent_ml_predictions(symbol, limit=1)
        if recent_preds:
            ml_predictions[symbol] = recent_preds[0]

    return jsonify({
        'metrics': metrics,
        'stats': stats,
        'ml_predictions': ml_predictions,  # Add ML predictions
        'timestamp': datetime.now(timezone.utc).isoformat()
    })


@app.route('/api/trades', methods=['GET'])
def get_trades():
    """Get trading history"""
    recent = history_db.get_recent_trades(limit=50)
    open_trades = history_db.get_open_trades_with_pnl()

    # Convert datetime objects to ISO format strings
    for trade in recent:
        if isinstance(trade['entry_time'], str):
            try:
                trade['entry_time'] = datetime.fromisoformat(trade['entry_time']).isoformat()
            except:
                pass
        if isinstance(trade['exit_time'], str):
            try:
                trade['exit_time'] = datetime.fromisoformat(trade['exit_time']).isoformat()
            except:
                pass

    # Add live P&L to open trades
    for trade in open_trades:
        if isinstance(trade['entry_time'], str):
            try:
                trade['entry_time'] = datetime.fromisoformat(trade['entry_time']).isoformat()
            except:
                pass

    return jsonify({
        'recent_trades': recent,
        'open_trades': open_trades,
        'timestamp': datetime.now(timezone.utc).isoformat()
    })


@app.route('/api/trades/<symbol>', methods=['GET'])
def get_symbol_trades(symbol):
    """Get trades for specific symbol"""
    recent = history_db.get_recent_trades(symbol, limit=50)
    open_trades = history_db.get_open_trades_with_pnl()
    stats = history_db.get_stats(symbol)

    return jsonify({
        'symbol': symbol,
        'recent_trades': recent,
        'open_trades': [t for t in open_trades if t['symbol'] == symbol],
        'stats': stats,
        'timestamp': datetime.now(timezone.utc).isoformat()
    })


@app.route('/api/live-pnl', methods=['GET'])
def get_live_pnl():
    """Get live P&L for all open trades"""
    open_trades = history_db.get_open_trades_with_pnl()
    
    # Get current prices and calculate live P&L
    for trade in open_trades:
        try:
            # Get current price from Binance
            binance_symbol = trade['symbol'].replace('/', '') + 'USDT'
            current_price = get_binance_current_price(binance_symbol)
            
            # Calculate live P&L
            entry_price = trade.get('entry_price', 0)
            side = trade.get('side', 'LONG')
            
            if side == 'LONG':
                live_pnl_pct = ((current_price - entry_price) / entry_price) * 100
            else:
                live_pnl_pct = ((entry_price - current_price) / entry_price) * 100
            
            trade['current_price'] = current_price
            trade['live_pnl_pct'] = live_pnl_pct
            trade['live_pnl_value'] = (current_price - entry_price) if side == 'LONG' else (entry_price - current_price)
        except Exception as e:
            trade['current_price'] = None
            trade['live_pnl_pct'] = None
            trade['live_pnl_value'] = None
    
    return jsonify({
        'open_trades': open_trades,
        'timestamp': datetime.now(timezone.utc).isoformat()
    })


@app.route('/api/ml-predictions', methods=['GET'])
def get_ml_predictions():
    """Get ML predictions for all coins"""
    # Get recent ML predictions from database
    recent_predictions = history_db.get_recent_ml_predictions(limit=100)
    
    # Group by symbol and get latest for each
    latest_by_symbol = {}
    for pred in recent_predictions:
        symbol = pred['symbol']
        if symbol not in latest_by_symbol:
            latest_by_symbol[symbol] = pred
    
    # Get trader state for live status
    predictions = {}
    for symbol in live_state['traders'].keys():
        trader = live_state['traders'][symbol]
        ml_data = latest_by_symbol.get(symbol, {})
        
        predictions[symbol] = {
            'symbol': symbol,
            'is_running': trader.get('is_running', False),
            'has_open_trade': trader.get('has_open_trade', False),
            'last_update': trader.get('last_update', None),
            'ml_prediction': {
                'predicted_class': ml_data.get('predicted_class'),
                'confidence': ml_data.get('confidence'),
                'breakout_prob': ml_data.get('breakout_prob'),
                'recommendation': ml_data.get('recommendation'),
                'tp_target': ml_data.get('tp_target'),
                'sl_limit': ml_data.get('sl_limit'),
                'timestamp': ml_data.get('timestamp')
            } if ml_data else None
        }
    
    return jsonify({
        'predictions': predictions,
        'recent_history': recent_predictions[:20],  # Last 20 for history table
        'timestamp': datetime.now(timezone.utc).isoformat()
    })


@app.route('/', methods=['GET'])
def dashboard():
    """Serve the dashboard HTML"""
    return render_template('index.html')


def update_trader_state(symbol: str, status: Dict):
    """Called by coin_trader to update state"""
    live_state['traders'][symbol] = status
    live_state['last_updated'] = datetime.now(timezone.utc).isoformat()


def start_api_server(port: int = 5000, debug: bool = False):
    """Start the Flask API server"""
    print(f"\n{'='*70}")
    print(f"🌐 STARTING TRADING DASHBOARD API")
    print(f"{'='*70}")
    print(f"📊 Dashboard available at: http://localhost:{port}")
    print(f"🔗 API Docs: http://localhost:{port}/api/*")
    print(f"{'='*70}\n")
    
    app.run(host='0.0.0.0', port=port, debug=debug, use_reloader=False)


def start_api_server_background(port: int = 5000):
    """Start API server in background thread"""
    thread = threading.Thread(target=start_api_server, args=(port, False), daemon=True)
    thread.start()
    time.sleep(2)  # Wait for server to start
    print(f"✅ API Server running on port {port}")
    return thread


if __name__ == '__main__':
    app.run(debug=True, port=5000)
