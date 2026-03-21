"""
binance_client.py
=================
Binance Exchange API Client (DATA ONLY)
Used for historical and real-time candle data
"""

import hmac
import hashlib
import time
import requests
from datetime import datetime, timezone
from typing import Optional, Dict, List
from config.settings import BINANCE_API_KEY, BINANCE_API_SECRET


# ================= UTILITY FUNCTIONS =================

def get_timestamp() -> int:
    """Return millisecond timestamp"""
    return int(time.time() * 1000)


def sign_request(query_params: dict = None) -> str:
    """Generate HMAC SHA256 signature for Binance"""
    if query_params is None:
        query_params = {}
    
    query_params['timestamp'] = get_timestamp()
    sorted_params = '&'.join(f"{k}={v}" for k, v in sorted(query_params.items()))
    signature = hmac.new(
        BINANCE_API_SECRET.encode('utf-8'),
        sorted_params.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    return signature


def binance_request(method: str, endpoint: str, params: dict = None, 
                    signed: bool = False) -> dict:
    """Make request to Binance API"""
    base_url = "https://api.binance.com"
    url = f"{base_url}{endpoint}"
    
    if params is None:
        params = {}
    
    if signed:
        params['timestamp'] = get_timestamp()
        params['signature'] = sign_request(params.copy())
        headers = {'X-MBX-APIKEY': BINANCE_API_KEY}
    else:
        headers = {}
    
    try:
        if method.upper() == 'GET':
            response = requests.get(url, headers=headers, params=params, timeout=10)
        elif method.upper() == 'POST':
            response = requests.post(url, headers=headers, data=params, timeout=10)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")
        
        response.raise_for_status()
        return response.json()
    
    except Exception as e:
        print(f"Binance API Error: {e}")
        return {}


# ================= MARKET DATA FUNCTIONS =================

def get_binance_current_price(symbol="ETHUSDT") -> float:
    """Get current market price from Binance"""
    try:
        params = {'symbol': symbol}
        data = binance_request('GET', '/api/v3/ticker/price', params, signed=False)
        if data and 'price' in data:
            return float(data['price'])
        return 0.0
    except Exception as e:
        print(f"Error fetching Binance price: {e}")
        return 0.0


def get_binance_ticker(symbol="ETHUSDT") -> dict:
    """Get 24hr ticker with volume, change, etc."""
    try:
        params = {'symbol': symbol}
        data = binance_request('GET', '/api/v3/ticker/24hr', params, signed=False)
        return data
    except Exception as e:
        print(f"Error fetching Binance ticker: {e}")
        return {}


def load_binance_historical_data(symbol="ETHUSDT", interval="15m", 
                                  days_back=3, limit=300) -> list:
    """Load historical OHLCV data from Binance"""
    try:
        params = {
            'symbol': symbol,
            'interval': interval,
            'limit': limit
        }
        data = binance_request('GET', '/api/v3/klines', params, signed=False)
        return data
    except Exception as e:
        print(f"Error loading Binance historical data: {e}")
        return []


def get_binance_latest_candle(symbol="ETHUSDT", interval="15m") -> list:
    """Get latest candle from Binance"""
    try:
        params = {
            'symbol': symbol,
            'interval': interval,
            'limit': 1
        }
        data = binance_request('GET', '/api/v3/klines', params, signed=False)
        return data
    except Exception as e:
        print(f"Error fetching latest Binance candle: {e}")
        return []