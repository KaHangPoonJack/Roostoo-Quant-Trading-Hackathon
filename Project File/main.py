import numpy as np
import pandas as pd
import time
from datetime import datetime, timezone, timedelta
from config.settings import ML_ENABLED, ML_MODEL_DIR
from data.fetcher import load_binance_historical_data, get_latest_binance_candle
from core.binance_client import get_binance_current_price
from core.utils import wait_until_next_quarter_hour
from core.telegram_bot import send_telegram_message
from strategies.chandelier_exit import ChandelierExit
from core.api_server import start_api_server_background
from trading.multi_coin_manager import manager
from daily_report import send_daily_report
import os
import warnings
import sys
import signal
import threading

os.environ['LOKY_MAX_CPU_COUNT'] = '4'
warnings.filterwarnings('ignore', category=UserWarning)
warnings.filterwarnings('ignore', category=DeprecationWarning)

if ML_ENABLED:
    print("✅ ML Filter enabled - trades require CE + ML agreement")
else:
    print("⚠️  ML Filter disabled - CE strategy only")

def signal_handler(sig, frame):
    """Handle Ctrl+C gracefully"""
    print("\n\n⚠️  Shutdown signal received...")
    manager.stop_all()
    sys.exit(0)

if __name__ == "__main__":
    try:
        # Start API server in background
        api_thread = start_api_server_background(port=5000)

        # Initialize all coin traders
        manager.initialize_all()

        # Start all traders in parallel
        manager.start_all()

        # ✅ START DAILY REPORT SCHEDULER
        def run_daily_report_scheduler():
            import schedule
            schedule.every().day.at("00:00").do(send_daily_report)
            print(f"\n{'='*70}")
            print(f"🕐 DAILY REPORT SCHEDULER STARTED")
            print(f"{'='*70}")
            print(f"⏰ Reports will be sent daily at UTC 00:00")
            print(f"📊 Next report: {(datetime.now(timezone.utc) + timedelta(days=1)).replace(hour=0, minute=0, second=0).strftime('%Y-%m-%d %H:%M:%S UTC')}")
            print(f"{'='*70}\n")
            
            while True:
                schedule.run_pending()
                time.sleep(60)
        
        report_thread = threading.Thread(target=run_daily_report_scheduler, daemon=True)
        report_thread.start()

        # Keep main thread alive
        print("\n✅ All traders running. Press Ctrl+C to stop.\n")
        print("📊 Dashboard: http://localhost:5000")
        print("🔗 API Docs: http://localhost:5000/api/*")
        print("🕐 Daily reports: Enabled (UTC 00:00)\n")

        while True:
            time.sleep(1)

    except Exception as e:
        print(f"❌ Fatal error: {e}")
        send_telegram_message(
            f"🚨 <b>BOT CRASHED</b>\n"
            f"├─ Error: {str(e)}\n"
            f"└─ Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )
        manager.stop_all()
        sys.exit(1)

    signal.signal(signal.SIGINT, signal_handler)