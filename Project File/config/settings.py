from dotenv import load_dotenv
import os
from pathlib import Path

load_dotenv()

# API Credentials
API_KEY = os.getenv("OKX_API_KEY")
API_SECRET = os.getenv("OKX_API_SECRET")
API_PASSPHRASE = os.getenv("OKX_PASSPHRASE")
BASE_URL = os.getenv("OKX_BASE_URL")

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")
BINANCE_SYMBOL = os.getenv("BINANCE_SYMBOL", "ETHUSDT")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

ROOSTOO_API_KEY = os.getenv("ROOSTOO_API_KEY")
ROOSTOO_SECRET_KEY = os.getenv("ROOSTOO_SECRET_KEY")
ROOSTOO_BASE_URL = os.getenv("ROOSTOO_BASE_URL", "https://mock-api.roostoo.com")
ROOSTOO_PAIR = os.getenv("ROOSTOO_PAIR", "ETH/USD")
ROOSTOO_BASE_CURRENCY = os.getenv("ROOSTOO_BASE_CURRENCY", "USD")

ROOSTOO_ENABLED = True
EXCHANGE_TYPE = os.getenv("EXCHANGE_TYPE", "ROOSTOO")  # OKX, BINANCE, or ROOSTOO

# Trading constants
INST_ID = "ETH-USDT-SWAP"
BAR_SIZE = "15m"
LEVERAGE = 1
POSITION_SIZE_PCT = 0.5

# ===== TAKE PROFIT / STOP LOSS SETTINGS =====
TP_SL_ENABLED = True

# Class-based Take Profit levels (based on ML predicted class)
TAKE_PROFIT_PCT = {
    1: 0.01,  # Class 1: 1% TP
    2: 0.03,  # Class 2: 3% TP
    3: 0.05   # Class 3: 5% TP
}

# Class-based Stop Loss levels (Risk-Reward Ratio 1:1 to 1:2)
STOP_LOSS_PCT = {
    1: 0.01,  # Class 1: 1% SL (RRR 1:1)
    2: 0.015, # Class 2: 1.5% SL (RRR 1:2)
    3: 0.025  # Class 3: 2.5% SL (RRR 1:2)
}

TP_SL_CHECK_INTERVAL = 2  # Check TP/SL every 2 seconds
LIMIT_ORDER_AT_TP = True  # Place limit order at TP level

PROJECT_ROOT = Path(__file__).parent.parent
ML_MODEL_DIR = PROJECT_ROOT / "ML" / "models"
ML_CONFIDENCE_THRESHOLD = 0.7
ML_ENABLED = True

# ===== ROOSTOO EXCHANGE SETTINGS =====
ROOSTOO_ENABLED = True  # Set True to use Roostoo, False for OKX
