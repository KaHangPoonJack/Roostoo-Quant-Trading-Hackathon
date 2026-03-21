"""
trading/multi_coin_manager.py
=============================
Manages multiple CoinTrader instances in parallel
"""

import time
import threading
from datetime import datetime, timezone
from typing import Dict, List
from trading.coin_trader import CoinTrader
from core.telegram_bot import send_telegram_message
from config.settings import ML_MODEL_DIR


class MultiCoinManager:
    """
    Manages multiple cryptocurrency traders running in parallel
    Each coin has independent ML model and CE strategy
    """
    
    def __init__(self):
        self.traders: Dict[str, CoinTrader] = {}
        self.is_running = False
        self.monitor_thread = None
        
        # Coin configuration
        self.coin_configs = [
            {
                'symbol': 'BTC',
                'binance_symbol': 'BTCUSDT',
                'roostoo_pair': 'BTC/USD',
                'model_dir': str(ML_MODEL_DIR / 'btc_models'),
                'allocation_pct': 1.0
            },
            {
                'symbol': 'ETH',
                'binance_symbol': 'ETHUSDT',
                'roostoo_pair': 'ETH/USD',
                'model_dir': str(ML_MODEL_DIR / 'eth_models'),
                'allocation_pct': 1.0
            },
            {
                'symbol': 'DOGE',
                'binance_symbol': 'DOGEUSDT',
                'roostoo_pair': 'DOGE/USD',
                'model_dir': str(ML_MODEL_DIR / 'doge_models'),
                'allocation_pct': 1.0
            },
            {
                'symbol': 'SOL',
                'binance_symbol': 'SOLUSDT',
                'roostoo_pair': 'SOL/USD',
                'model_dir': str(ML_MODEL_DIR / 'sol_models'),
                'allocation_pct': 1.0
            },
            {
                'symbol': 'PEPE',
                'binance_symbol': 'PEPEUSDT',
                'roostoo_pair': 'PEPE/USD',
                'model_dir': str(ML_MODEL_DIR / 'pepe_models'),
                'allocation_pct': 1.0
            }
        ]
    
    def initialize_all(self):
        """Initialize all coin traders"""
        print("\n" + "="*70)
        print("🚀 INITIALIZING MULTI-COIN TRADING BOT")
        print("="*70)
        
        for config in self.coin_configs:
            try:
                trader = CoinTrader(
                    symbol=config['symbol'],
                    binance_symbol=config['binance_symbol'],
                    roostoo_pair=config['roostoo_pair'],
                    model_dir=config['model_dir'],
                    allocation_pct=config['allocation_pct']
                )
                trader.initialize()
                self.traders[config['symbol']] = trader
                print(f"✅ {config['symbol']}: Initialized")
            except Exception as e:
                print(f"❌ {config['symbol']}: Failed to initialize - {e}")
        
        print(f"\n✅ {len(self.traders)}/{len(self.coin_configs)} coins ready")
        print("="*70 + "\n")
    
    def start_all(self):
        """Start all coin traders in parallel"""
        print("\n🚀 STARTING ALL TRADERS\n")
        
        for symbol, trader in self.traders.items():
            trader.start()
            time.sleep(1)  # Stagger starts slightly
        
        self.is_running = True
        
        # ✅ REMOVED: 5-minute status update thread
        # P&L updates now handled by individual CoinTrader every 15min
        
        # Send startup notification
        send_telegram_message(
            f"🚀 <b>MULTI-COIN TRADING BOT STARTED</b>\n"
            f"├─ Coins: {', '.join(self.traders.keys())}\n"
            f"├─ Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
            f"└─ Each coin has independent ML model + CE strategy"
        )
    
    def stop_all(self):
        """Stop all coin traders"""
        print("\n⏹️ STOPPING ALL TRADERS\n")
        
        self.is_running = False
        
        for symbol, trader in self.traders.items():
            trader.stop()
        
        send_telegram_message(
            f"⏹️ <b>MULTI-COIN TRADING BOT STOPPED</b>\n"
            f"└─ Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )
    
    def get_all_status(self) -> Dict:
        """Get status from all traders"""
        from core.api_server import update_trader_state
        
        statuses = {}
        for symbol, trader in self.traders.items():
            status = trader.get_status()
            statuses[symbol] = status
            # Update API state
            update_trader_state(symbol, status)
        
        return statuses
    
    def restart_trader(self, symbol: str):
        """Restart a specific coin trader"""
        if symbol in self.traders:
            self.traders[symbol].stop()
            time.sleep(2)
            self.traders[symbol].start()
            print(f"🔄 {symbol}: Restarted")


# Global manager instance
manager = MultiCoinManager()