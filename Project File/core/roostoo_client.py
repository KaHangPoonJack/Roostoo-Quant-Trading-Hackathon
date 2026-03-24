"""
roostoo_client.py
=================
Roostoo Exchange API Client
EXACTLY matching bot.py working pattern
Credentials from config/settings.py (not hardcoded)
"""

import json
import hmac
import hashlib
import time
import requests
from datetime import datetime, timezone
from typing import Optional, Dict, List, Tuple

# Import credentials from settings (NOT hardcoded)
from config.settings import ROOSTOO_API_KEY, ROOSTOO_SECRET_KEY, ROOSTOO_BASE_URL


# ================= UTILITY FUNCTIONS =================

def get_timestamp() -> str:
    """Return 13-digit millisecond timestamp"""
    return str(int(time.time() * 1000))


def get_signed_headers(payload: dict = None):
    """
    Generate signed headers for RCL_TopLevelCheck endpoints
    EXACTLY like bot.py - NO Content-Type here!
    """
    if payload is None:
        payload = {}
    
    payload['timestamp'] = get_timestamp()
    sorted_keys = sorted(payload.keys())
    total_params = "&".join(f"{k}={payload[k]}" for k in sorted_keys)
    
    signature = hmac.new(
        ROOSTOO_SECRET_KEY.encode('utf-8'),
        total_params.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    # NO Content-Type header here (like bot.py)
    headers = {
        'RST-API-KEY': ROOSTOO_API_KEY,
        'MSG-SIGNATURE': signature
    }
    
    return headers, payload, total_params


# ================= PUBLIC ENDPOINTS (No Auth Required) =================

def check_server_time() -> Optional[Dict]:
    """Check API server time"""
    url = f"{ROOSTOO_BASE_URL}/v3/serverTime"
    try:
        res = requests.get(url, timeout=10)
        res.raise_for_status()
        return res.json()
    except requests.exceptions.RequestException as e:
        print(f"Error checking server time: {e}")
        return None


def get_exchange_info() -> Optional[Dict]:
    """Get exchange trading pairs and info"""
    url = f"{ROOSTOO_BASE_URL}/v3/exchangeInfo"
    try:
        res = requests.get(url, timeout=10)
        res.raise_for_status()
        return res.json()
    except requests.exceptions.RequestException as e:
        print(f"Error getting exchange info: {e}")
        return None


def get_ticker(pair: str = None) -> Optional[Dict]:
    """Get ticker for one or all pairs"""
    url = f"{ROOSTOO_BASE_URL}/v3/ticker"
    params = {'timestamp': get_timestamp()}
    if pair:
        params['pair'] = pair
    try:
        res = requests.get(url, params=params, timeout=10)
        res.raise_for_status()
        return res.json()
    except requests.exceptions.RequestException as e:
        print(f"Error getting ticker: {e}")
        return None


# ================= SIGNED ENDPOINTS (Auth Required) =================

def get_balance() -> Optional[Dict]:
    """Get wallet balances (RCL_TopLevelCheck)"""
    url = f"{ROOSTOO_BASE_URL}/v3/balance"
    headers, payload, _ = get_signed_headers({})
    try:
        res = requests.get(url, headers=headers, params=payload, timeout=10)
        res.raise_for_status()
        return res.json()
    except requests.exceptions.RequestException as e:
        print(f"Error getting balance: {e}")
        print(f"Response text: {e.response.text if e.response else 'N/A'}")
        return None


def get_pending_count() -> Optional[Dict]:
    """Get total pending order count"""
    url = f"{ROOSTOO_BASE_URL}/v3/pending_count"
    headers, payload, _ = get_signed_headers({})
    try:
        res = requests.get(url, headers=headers, params=payload, timeout=10)
        res.raise_for_status()
        return res.json()
    except requests.exceptions.RequestException as e:
        print(f"Error getting pending count: {e}")
        print(f"Response text: {e.response.text if e.response else 'N/A'}")
        return None


def place_order(pair_or_coin: str, side: str, quantity: str, 
                price: float = None, order_type: str = None) -> Optional[Dict]:
    """
    Place a LIMIT or MARKET order
    """
    url = f"{ROOSTOO_BASE_URL}/v3/place_order"
    pair = f"{pair_or_coin}/USD" if "/" not in pair_or_coin else pair_or_coin
    
    if order_type is None:
        order_type = "LIMIT" if price is not None else "MARKET"
    
    if order_type == 'LIMIT' and price is None:
        print("Error: LIMIT orders require 'price'.")
        return None
    
    payload = {
        'pair': pair,
        'side': side.upper(),
        'type': order_type.upper(),
        'quantity': str(quantity)
    }
    if order_type == 'LIMIT':
        payload['price'] = str(price)
    
    # POST request - ADD Content-Type HERE (like bot.py)
    headers, _, total_params = get_signed_headers(payload)
    headers['Content-Type'] = 'application/x-www-form-urlencoded'
    
    try:
        res = requests.post(url, headers=headers, data=total_params, timeout=10)
        res.raise_for_status()
        return res.json()
    except requests.exceptions.RequestException as e:
        print(f"Error placing order: {e}")
        print(f"Response text: {e.response.text if e.response else 'N/A'}")
        return None


def query_order(order_id: str = None, pair: str = None, 
                pending_only: bool = None) -> Optional[Dict]:
    """Query order history or pending orders"""
    url = f"{ROOSTOO_BASE_URL}/v3/query_order"
    payload = {}
    if order_id:
        payload['order_id'] = str(order_id)
    elif pair:
        payload['pair'] = pair
        if pending_only is not None:
            payload['pending_only'] = 'TRUE' if pending_only else 'FALSE'
    
    # POST request - ADD Content-Type HERE (like bot.py)
    headers, _, total_params = get_signed_headers(payload)
    headers['Content-Type'] = 'application/x-www-form-urlencoded'
    
    try:
        res = requests.post(url, headers=headers, data=total_params, timeout=10)
        res.raise_for_status()
        return res.json()
    except requests.exceptions.RequestException as e:
        print(f"Error querying order: {e}")
        print(f"Response text: {e.response.text if e.response else 'N/A'}")
        return None


def cancel_order(order_id: str = None, pair: str = None) -> Optional[Dict]:
    """Cancel specific or all pending orders"""
    url = f"{ROOSTOO_BASE_URL}/v3/cancel_order"
    payload = {}
    if order_id:
        payload['order_id'] = str(order_id)
    elif pair:
        payload['pair'] = pair
    
    # POST request - ADD Content-Type HERE (like bot.py)
    headers, _, total_params = get_signed_headers(payload)
    headers['Content-Type'] = 'application/x-www-form-urlencoded'
    
    try:
        res = requests.post(url, headers=headers, data=total_params, timeout=10)
        res.raise_for_status()
        return res.json()
    except requests.exceptions.RequestException as e:
        print(f"Error canceling order: {e}")
        print(f"Response text: {e.response.text if e.response else 'N/A'}")
        return None


# ================= HELPER FUNCTIONS FOR TRADING BOT =================

def get_roostoo_account_info() -> Dict:
    """Get account balance information (wrapper)"""
    data = get_balance()
    return data if data else {}


def get_roostoo_balance(ccy: str = "USD") -> float:
    """Get balance for a specific currency"""
    data = get_balance()
    
    if not data:
        return 0.0
    
    # Handle both 'Wallet' and 'SpotWallet' formats
    wallet = data.get('Wallet', {}) or data.get('SpotWallet', {})

    if ccy in wallet:
        free_bal = wallet[ccy].get('Free', 0)
        return float(free_bal) if free_bal else 0.0
    
    return 0.0


def get_roostoo_pending_count() -> Dict:
    """Get pending order count (wrapper)"""
    data = get_pending_count()
    return data if data else {'TotalPending': 0, 'OrderPairs': {}}


def get_roostoo_current_price(pair: str = "ETH/USD") -> float:
    """Get current market price for a trading pair"""
    data = get_ticker(pair)
    if data and data.get('Success') and 'Data' in data:
        pair_data = data['Data'].get(pair, {})
        last_price = pair_data.get('LastPrice', 0)
        return float(last_price) if last_price else 0.0
    return 0.0


def calculate_roostoo_order_size(usd_amount: float, coin_price: float,
                                  price_precision: int = 2,
                                  amount_precision: int = 2,
                                  mini_order: float = 1.0) -> str:
    """Calculate valid order size for Roostoo spot trading"""
    coin_amount = usd_amount / coin_price

    # For low-priced coins, use INTEGER quantities (no decimals)
    # This is required by the exchange to avoid "quantity step size error"
    if coin_price < 0.01:
        # For coins < $0.01, use integer quantities only
        valid_amount = int(coin_amount)
        amount_precision = 0
    elif coin_price < 0.1:
        # For coins < $0.10, use 2 decimals
        amount_precision = 2
        precision_multiplier = 10 ** amount_precision
        valid_amount = int(coin_amount * precision_multiplier) / precision_multiplier
    else:
        # For normal coins, use standard precision
        precision_multiplier = 10 ** amount_precision
        valid_amount = int(coin_amount * precision_multiplier) / precision_multiplier

    order_value = valid_amount * coin_price
    if order_value < mini_order:
        valid_amount = mini_order / coin_price
        if coin_price < 0.01:
            valid_amount = int(valid_amount)
        else:
            precision_multiplier = 10 ** amount_precision
            valid_amount = int(valid_amount * precision_multiplier) / precision_multiplier

    if amount_precision == 0:
        return f"{int(valid_amount)}"
    else:
        return f"{valid_amount:.{amount_precision}f}"


def place_roostoo_order(pair: str = "ETH/USD",
                        side: str = "BUY",
                        order_type: str = "MARKET",
                        quantity: str = None,
                        price: float = None) -> Optional[str]:
    """Place an order on Roostoo (returns order_id)"""
    data = place_order(pair_or_coin=pair, side=side, quantity=quantity,
                       price=price, order_type=order_type)

    if data and data.get('Success'):
        order_detail = data.get('OrderDetail', {})
        order_id = order_detail.get('OrderID')
        status = order_detail.get('Status')
        print(f"✅ Order placed: ID={order_id}, Status={status}")
        return str(order_id)
    else:
        # Log the error for debugging
        error_msg = data.get('Message', 'Unknown error') if data else 'No response'
        print(f"❌ Order FAILED for {pair}: {error_msg}")
        print(f"   Quantity: {quantity}")
        print(f"   Full Response: {data}")
        return None


def query_roostoo_order(order_id: str = None, pair: str = None, 
                        pending_only: bool = False) -> List:
    """Query order history (returns list of orders)"""
    data = query_order(order_id=order_id, pair=pair, pending_only=pending_only)
    if data and data.get('Success'):
        return data.get('OrderMatched', [])
    return []


def cancel_roostoo_order(order_id: str = None, pair: str = None) -> List:
    """Cancel pending order(s) (returns list of canceled order IDs)"""
    data = cancel_order(order_id=order_id, pair=pair)
    if data and data.get('Success'):
        return data.get('CanceledList', [])
    return []


def close_roostoo_position(pair: str = "ETH/USD", side: str = "SELL") -> Optional[str]:
    """Close position by placing opposite market order"""
    # Get current balance to know how much to sell
    balance_data = get_balance()
    if not balance_data:
        print("⚠️ Could not fetch balance to close position")
        return None
    
    wallet = balance_data.get('Wallet', {}) or balance_data.get('SpotWallet', {})
    coin = pair.split('/')[0]
    
    if coin in wallet:
        free_balance = wallet[coin].get('Free', 0)
        if free_balance and float(free_balance) > 0:
            return place_roostoo_order(
                pair=pair,
                side=side,
                order_type="MARKET",
                quantity=str(free_balance)
            )
    
    print("⚠️ No position to close")
    return None


def get_roostoo_position(pair: str = "ETH/USD") -> Tuple[float, float]:
    """
    Get current position for spot trading
    Returns: (coin_balance, avg_price)
    For spot, we return balance instead of futures position
    """
    coin = pair.split('/')[0]
    balance_data = get_balance()
    
    if not balance_data:
        return 0.0, 0.0
    
    wallet = balance_data.get('Wallet', {}) or balance_data.get('SpotWallet', {})
    
    if coin in wallet:
        free_balance = float(wallet[coin].get('Free', 0))
        return free_balance, 0.0  # Spot doesn't track avg price
    
    return 0.0, 0.0


# ================= LEVERAGE/POSITION MODE (NOT SUPPORTED ON ROOSTOO) =================

def set_roostoo_leverage(inst_id: str = "ETH/USD", lever: int = 1, 
                         mgn_mode: str = "spot") -> Dict:
    """Roostoo is spot-only, leverage not supported"""
    print("⚠️ Roostoo is spot-only trading. Leverage not supported.")
    return {'Success': True, 'Msg': 'Leverage not applicable for spot trading'}


def set_roostoo_position_mode(pos_mode: str = "spot") -> Dict:
    """Roostoo doesn't have position modes like OKX"""
    print("⚠️ Roostoo doesn't support position modes (spot trading only)")
    return {'Success': True, 'Msg': 'Position mode not applicable'}


# ================= HELPER FOR IMPORTS =================

def get_roostoo_client():
    """Helper so other files can import easily"""
    return None