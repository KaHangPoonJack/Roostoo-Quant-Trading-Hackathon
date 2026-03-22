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


@app.route('/api/balance', methods=['GET'])
def get_balance():
    """Get Roostoo account balance"""
    try:
        from core.roostoo_client import get_roostoo_balance
        from config.settings import ROOSTOO_BASE_CURRENCY
        
        # Get USD balance
        usd_balance = get_roostoo_balance(ROOSTOO_BASE_CURRENCY)
        
        return jsonify({
            'balances': {'USD': usd_balance},
            'total_usd': usd_balance if usd_balance else 0,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
    except Exception as e:
        print(f"❌ Balance API error: {e}")
        return jsonify({
            'error': str(e),
            'total_usd': 0,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }), 500


@app.route('/api/holdings', methods=['GET'])
def get_holdings():
    """Get all asset holdings from Roostoo"""
    try:
        from core.roostoo_client import get_balance as roostoo_get_balance
        
        # Get full balance data
        data = roostoo_get_balance()
        
        if not data:
            return jsonify({
                'holdings': [],
                'total_usd': 0,
                'timestamp': datetime.now(timezone.utc).isoformat()
            })
        
        # Handle both 'Wallet' and 'SpotWallet' formats
        wallet = data.get('Wallet', {}) or data.get('SpotWallet', {})
        
        # Parse holdings
        holdings = []
        total_usd = 0
        
        for ccy, balances in wallet.items():
            if isinstance(balances, dict):
                free = float(balances.get('Free', 0) or 0)
                locked = float(balances.get('Locked', 0) or 0)
                total = free + locked
                
                if total > 0:
                    holdings.append({
                        'currency': ccy,
                        'free': free,
                        'locked': locked,
                        'total': total
                    })
                    
                    # Simple USD conversion (for non-USD, would need price API)
                    if ccy == 'USD':
                        total_usd += total
        
        return jsonify({
            'holdings': holdings,
            'total_usd': total_usd,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
    except Exception as e:
        print(f"❌ Holdings API error: {e}")
        return jsonify({
            'error': str(e),
            'holdings': [],
            'total_usd': 0,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }), 500


@app.route('/api/traders', methods=['GET'])
def get_traders():
    """Get status of all traders"""
    return jsonify({
        'traders': live_state['traders'],
        'timestamp': datetime.now(timezone.utc).isoformat()
    })


@app.route('/api/traders/refresh', methods=['POST'])
def refresh_traders():
    """Refresh trader status with actual Roostoo positions"""
    from core.roostoo_client import get_roostoo_position
    
    # Update each trader's actual position
    for symbol, trader in live_state['traders'].items():
        try:
            # Get actual position from Roostoo
            roostoo_pair = f"{symbol}/USD"
            pos_size, avg_price = get_roostoo_position(pair=roostoo_pair)
            
            # If Roostoo returns 0 for entry price, check database for open trade
            if pos_size > 0.001 and (avg_price == 0 or avg_price is None):
                open_trades = history_db.get_open_trades_with_pnl()
                for trade in open_trades:
                    if trade['symbol'] == symbol:
                        avg_price = trade.get('entry_price', 0)
                        break
            
            # Update trader state with actual position
            trader['has_open_trade'] = pos_size > 0.001 and avg_price > 0
            trader['actual_position_size'] = pos_size
            trader['actual_entry_price'] = avg_price if (pos_size > 0.001 and avg_price > 0) else 0
            
        except Exception as e:
            print(f"⚠️  {symbol}: Error checking position: {e}")
            trader['has_open_trade'] = False
            trader['actual_position_size'] = 0
            trader['actual_entry_price'] = 0
    
    live_state['last_updated'] = datetime.now(timezone.utc).isoformat()
    
    return jsonify({
        'traders': live_state['traders'],
        'timestamp': live_state['last_updated']
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
    from core.roostoo_client import get_roostoo_position
    
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
    
    # Get ACTUAL position from Roostoo for each symbol
    for symbol in metrics.keys():
        try:
            roostoo_pair = f"{symbol}/USD"
            pos_size, avg_price = get_roostoo_position(pair=roostoo_pair)
            
            # If Roostoo returns 0 for entry price, check database for open trade
            if pos_size > 0.001 and (avg_price == 0 or avg_price is None):
                # Query database for most recent open trade
                open_trades = history_db.get_open_trades_with_pnl()
                for trade in open_trades:
                    if trade['symbol'] == symbol:
                        avg_price = trade.get('entry_price', 0)
                        break
            
            # Update metrics with actual position data - STRICT CHECK
            metrics[symbol]['actual_position_size'] = pos_size if pos_size else 0
            metrics[symbol]['actual_entry_price'] = avg_price if (avg_price and avg_price > 0) else 0
            # Only show as open trade if BOTH position size > 0 AND entry price > 0
            metrics[symbol]['open_trade'] = (pos_size and pos_size > 0.001) and (avg_price and avg_price > 0)
            
        except Exception as e:
            print(f"⚠️  {symbol}: Error getting position: {e}")
            metrics[symbol]['actual_position_size'] = 0
            metrics[symbol]['actual_entry_price'] = 0
            metrics[symbol]['open_trade'] = False

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
    
    # Disable Flask request logging
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    
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
