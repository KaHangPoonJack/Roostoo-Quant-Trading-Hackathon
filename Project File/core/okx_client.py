import json
import hmac
import hashlib
import base64
import requests
import time
from datetime import datetime, timezone
# UTC timezone - use timezone.utc for Python 3.9 compatibility
try:
    from datetime import UTC  # Python 3.11+
except ImportError:
    UTC = timezone.utc  # Python 3.9-3.10
from typing import Optional, Dict, List, Union
from config.settings import API_KEY, API_SECRET, API_PASSPHRASE, BASE_URL

def get_timestamp() -> str:
    return datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'

def sign_request(method: str, request_path: str, query_params: Optional[Dict] = None, body: Optional[Dict] = None) -> tuple[str, str]:
    timestamp = get_timestamp()
    body_str = json.dumps(body, separators=(',', ':')) if body else ''
    
    # Handle query parameters as part of path (even for signature generation)
    if query_params:
        # OKX requires parameters sorted alphabetically by key
        sorted_params = sorted(query_params.items(), key=lambda x: x[0])
        query_str = '&'.join([f"{k}={v}" for k, v in sorted_params])
        request_path_with_params = f"{request_path}?{query_str}"
    else:
        request_path_with_params = request_path
    
    # Prehash = timestamp + method + full_path + body_str
    prehash = timestamp + method.upper() + request_path_with_params + body_str

    signature = hmac.new(
    API_SECRET.encode('utf-8'),
    prehash.encode('utf-8'),
    hashlib.sha256
    ).digest()  # Get raw bytes first
    signature = base64.b64encode(signature).decode('utf-8')
    
    return timestamp, signature

def okx_request(method: str, endpoint: str, query_params: Optional[Dict] = None, 
                body: Optional[Dict] = None) -> List[Dict]:
    timestamp, signature = sign_request(method, endpoint, query_params, body)
    
    headers = {
        'Content-Type': 'application/json',
        'OK-ACCESS-KEY': API_KEY,
        'OK-ACCESS-SIGN': signature,
        'OK-ACCESS-TIMESTAMP': timestamp,
        'OK-ACCESS-PASSPHRASE': API_PASSPHRASE
    }
    
    url = BASE_URL.rstrip('/') + endpoint
    
    if query_params:
        sorted_params = sorted(query_params.items())
        query_string = '&'.join([f"{k}={v}" for k, v in sorted_params])
        url += '?' + query_string
    
    if method.upper() == 'GET':
        response = requests.get(url, headers=headers, timeout=10)
    elif method.upper() == 'POST':
        body_str = json.dumps(body, separators=(',', ':')) if body else ''
        response = requests.post(url, headers=headers, data=body_str, timeout=10)
    else:
        raise ValueError(f"Unsupported HTTP method: {method}")
    
    if response.status_code != 200:
        raise Exception(f"OKX API Error ({response.status_code}): {response.text}")
    
    data = response.json()
    if data.get('code') != '0':
        raise Exception(f"OKX API Error [{data.get('code')}]: {data.get('msg')}")
    
    return data.get('data', [])

# Then ALL these functions:
def get_okx_account_info() -> Dict:
    """Get account configuration - returns first item in data array"""
    endpoint = "/api/v5/account/config"
    data = okx_request('GET', endpoint)
    # OKX returns data as an array with one config object
    return data[0] if data and isinstance(data, list) else {}

def get_okx_balance(ccy="USDT") -> float:
    """
    Get balance for a specific currency in the account
    """
    try:
        endpoint = "/api/v5/account/balance"
        params = {"ccy": ccy}
        data = okx_request('GET', endpoint, params)
    
        if data and isinstance(data, list) and len(data) > 0:
            for bal in data[0]['details']:
                if bal['ccy'] == ccy:
                    # Safely convert to float with fallback
                    avail_bal = bal.get('availBal', '0')
                    return float(avail_bal) if avail_bal.strip() else 0.0
        return 0.0
    except Exception as e:
        print(f"Error getting balance: {e}")
        return 0.0

def set_okx_position_mode(pos_mode: str = "net") -> Dict:
    """
    Set position mode: "net" or "long_short_mode"
    """
    endpoint = "/api/v5/account/set-position-mode"
    body = {"posMode": pos_mode}
    return okx_request('POST', endpoint, body=body)

def get_okx_position(inst_id="ETH-USDT-SWAP") -> tuple[float, float]:
    """
    Get current position for a specific instrument
    Returns position size (positive for long, negative for short) and entry price
    """
    endpoint = "/api/v5/account/positions"
    params = {"instId": inst_id}
    positions = okx_request('GET', endpoint, params)
    
    if positions:
        for pos in positions:
            if pos.get('instId') == inst_id:
                pos_str = pos.get('pos', '0')
                avg_px_str = pos.get('avgPx', '0')
                
                # Safely convert to float; treat empty/missing as 0.0
                try:
                    pos_size = float(pos_str) if pos_str.strip() else 0.0
                except (ValueError, AttributeError):
                    pos_size = 0.0
                
                try:
                    avg_px = float(avg_px_str) if avg_px_str.strip() else 0.0
                except (ValueError, AttributeError):
                    avg_px = 0.0
                
                return pos_size, avg_px
    
    return 0.0, 0.0

def get_okx_current_price(inst_id="ETH-USDT-SWAP") -> float:
    """Get current market price - this is a public endpoint but we'll use consistent format"""
    params = {"instId": inst_id}
    try:
        data = okx_request('GET', "/api/v5/market/ticker", params)
        if data and len(data) > 0:
            return float(data[0]['last'])
        return 0.0
    except Exception as e:
        print(f"Error fetching current price: {e}")
        return 0.0

#################################################
###  Trading Functions with Leverage Support
#################################################

def set_okx_leverage(inst_id: str = "ETH-USDT-SWAP", lever: int = 3, mgn_mode: str = "cross") -> Dict:
    """
    Set leverage for a specific instrument in SWAP account
    lever: leverage value (e.g., 3 for 3x)
    mgn_mode: "cross" or "isolated"
    """
    endpoint = "/api/v5/account/set-leverage"
    body = {
        "instId": inst_id,
        "lever": str(lever),
        "mgnMode": mgn_mode,
        "posSide": "net"  # Using net mode for simplicity
    }
    return okx_request('POST', endpoint, body=body)

def calculate_valid_order_size(usd_amount, eth_price, lot_sz=0.01, ct_val=0.1) -> str:
    """
    Calculate valid order size in contracts for OKX SWAP
    Returns properly formatted string size that respects lot size requirements
    """
    # Convert USD to ETH
    eth_amount = usd_amount / eth_price
    
    # Convert ETH to contracts (1 contract = ct_val ETH)
    contract_amount = eth_amount / ct_val
    
    # Round down to nearest lot size
    valid_contracts = (contract_amount // lot_sz) * lot_sz
    
    # Ensure it's at least minimum size (0.01 contracts)
    if valid_contracts < 0.01:
        return "0.01"
    
    # Format as string and remove trailing zeros
    size_str = f"{valid_contracts:.6f}".rstrip('0').rstrip('.')
    return size_str

def place_okx_order(inst_id="ETH-USDT-SWAP", side="buy", ord_type="market", 
                   size=None, price=None, td_mode="cross", pos_side="net"):
    """
    Place an order on OKX SWAP account - EXACTLY matching OKX documentation
    
    For SWAP Market Orders (required parameters):
    - instId: "ETH-USDT-SWAP"
    - tdMode: "cross" (cross margin mode)
    - side: "buy" or "sell"
    - posSide: "net" (required for SWAP in net mode)
    - ordType: "market"
    - sz: size in ETH contracts (string format)
    """
    endpoint = "/api/v5/trade/order"
    
    # Validate required parameters for market orders
    if ord_type == "market" and size is None:
        raise ValueError("Size (sz) is required for market orders")
    
    # Build body EXACTLY as OKX documentation requires
    body = {
        "instId": inst_id,    # REQUIRED: Instrument ID
        "tdMode": td_mode,    # REQUIRED: Trade mode (cross for SWAP)
        "side": side,         # REQUIRED: "buy" or "sell"
        "ordType": ord_type,  # REQUIRED: "market" for market orders
        "sz": size            # REQUIRED: Size in contract units (string)
    }
    
    # posSide is CONDITIONAL but REQUIRED for SWAP in net/long-short mode
    if pos_side:
        body["posSide"] = pos_side  # "net" for net mode
    
    # Price only needed for limit orders
    if price and ord_type != "market":
        body["px"] = price
    
    print("📡 Placing order with parameters:", json.dumps(body, indent=2))
    
    response = okx_request('POST', endpoint, body=body)
    if response and isinstance(response, list) and len(response) > 0:
        return response[0]['ordId']
    return None

def close_okx_position(inst_id="ETH-USDT-SWAP", td_mode="cross", pos_side="net"):
    """
    Close entire position for a specific instrument
    """
    # Get current position
    pos_size, entry_price = get_okx_position(inst_id)
    
    if abs(pos_size) < 0.001:  # Small threshold to avoid floating point issues
        print("⚠️ No significant position to close")
        return None
    
    # Determine side based on position size
    side = "sell" if pos_size > 0 else "buy"
    
    # Format size correctly - use absolute value with proper precision
    size_str = f"{abs(pos_size):.6f}".rstrip('0').rstrip('.')
    print(f"CloseOperation: Closing {size_str} contracts ({side} order)")
    
    # Place market order to close position
    return place_okx_order(
        inst_id=inst_id,
        side=side,
        ord_type="market",
        size=size_str,  # Properly formatted string
        td_mode=td_mode,
        pos_side=pos_side
    )

# At the bottom add:
def get_okx_client():
    """Helper so other files can import easily"""
    return None  # we don't need a class yet