import pandas as pd
from datetime import datetime
from core.okx_client import okx_request
from config.settings import INST_ID, BAR_SIZE, BINANCE_SYMBOL
from core.binance_client import (
    load_binance_historical_data as binance_klines,
    get_binance_latest_candle
)
from config.settings import BINANCE_SYMBOL, BAR_SIZE

def load_okx_historical_data(inst_id=INST_ID, days_back=1, bar=BAR_SIZE):
    """
    Load historical OHLCV data from OKX for SWAP contracts
    inst_id format for swaps: "ETH-USDT-SWAP"
    bar options: "15m", "1H", "4H", etc.
    """
    # Convert bar size to seconds for calculation
    bar_to_seconds = {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "1H": 3600,
        "4H": 14400,
        "1D": 86400
    }
    
    seconds_per_bar = bar_to_seconds.get(bar, 900)
    limit = min(100, int(days_back * 24 * 60 / (seconds_per_bar / 60)))
    
    # Calculate timestamps
    end_time = datetime.utcnow()
    start_time = end_time - pd.Timedelta(days=days_back)
    
    endpoint = "/api/v5/market/candles"
    params = {
        "instId": inst_id,
        "bar": bar,
        "limit": str(limit),
        "after": str(int(end_time.timestamp() * 1000)),
        "before": str(int(start_time.timestamp() * 1000))
    }
    
    print(f"Downloading {days_back} days of {inst_id} {bar} data from OKX...")
    
    try:
        data = okx_request('GET', endpoint, params)
        
        if not data:
            raise Exception("No data returned from OKX")

        # Convert to DataFrame
        candles = data
        df = pd.DataFrame(candles, columns=['time', 'open', 'high', 'low', 'close', 'volume', 'volCcy', 'volCcyQuote', 'confirm'])
        df['datetime'] = pd.to_datetime(df['time'].astype(int), unit='ms')
        df = df.sort_values('datetime').set_index('datetime')
        df = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
        df.columns = ['Open', 'High', 'Low', 'Close', 'Volume']
        
        print(f"Loaded {len(df)} {bar} bars from {df.index[0]} to {df.index[-1]}")
        return df
        
    except Exception as e:
        print(f"Error loading historical data: {e}")
        raise

def get_latest_okx_candles(inst_id=INST_ID, limit=1, bar=BAR_SIZE):
    """
    Fetch latest candles from OKX
    """
    params = {
        "instId": inst_id,
        "bar": bar,
        "limit": str(limit)
    }
    data = okx_request('GET', "/api/v5/market/candles", params)
    if not data:
        print("No candle data returned from OKX")
        return pd.DataFrame()
    
    # Convert to DataFrame
    candles = data
    df = pd.DataFrame(candles, columns=['time', 'open', 'high', 'low', 'close', 'volume', 'volCcy', 'volCcyQuote', 'confirm'])
    df['datetime'] = pd.to_datetime(df['time'].astype(int), unit='ms')
    df = df.sort_values('datetime').set_index('datetime')
    df = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
    df.columns = ['Open', 'High', 'Low', 'Close', 'Volume']
        
    print(f"Fetched {len(df)} new {bar} bars from OKX: {df.index[-1]}")
    return df

def load_binance_historical_data(symbol=BINANCE_SYMBOL, interval=BAR_SIZE, 
                                  days_back=3, limit=300):
    """
    Load historical OHLCV data from Binance
    Returns DataFrame compatible with strategy
    """
    from core.binance_client import load_binance_historical_data as binance_klines
    
    print(f"Downloading {days_back} days of {symbol} {interval} data from Binance...")
    
    try:
        candles = binance_klines(symbol=symbol, interval=interval, 
                                 days_back=days_back, limit=limit)
        
        if not candles:
            raise Exception("No data returned from Binance")
        
        # Convert to DataFrame
        df = pd.DataFrame(candles, columns=[
            'time', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_vol', 'trades', 'taker_buy_base', 
            'taker_buy_quote', 'ignore'
        ])
        
        df['datetime'] = pd.to_datetime(df['time'].astype(int), unit='ms')
        df = df.sort_values('datetime').set_index('datetime')
        df = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
        df.columns = ['Open', 'High', 'Low', 'Close', 'Volume']
        
        print(f"Loaded {len(df)} {interval} bars from {df.index[0]} to {df.index[-1]}")
        return df
    
    except Exception as e:
        print(f"Error loading Binance historical data: {e}")
        raise

def get_latest_binance_candle(symbol="ETHUSDT", interval="15m"):
    """
    Fetch latest candle from Binance
    Returns single candle DataFrame
    """
    from core.binance_client import get_binance_latest_candle
    
    try:
        candles = get_binance_latest_candle(symbol=symbol, interval=interval)
        
        if not candles:
            print("No candle data returned from Binance")
            return pd.DataFrame()
        
        # Convert to DataFrame
        df = pd.DataFrame(candles, columns=[
            'time', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_vol', 'trades', 'taker_buy_base', 
            'taker_buy_quote', 'ignore'
        ])
        
        df['datetime'] = pd.to_datetime(df['time'].astype(int), unit='ms')
        df = df.sort_values('datetime').set_index('datetime')
        df = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
        df.columns = ['Open', 'High', 'Low', 'Close', 'Volume']
        
        print(f"Fetched {len(df)} new {interval} bar from Binance: {df.index[-1]}")
        return df
    
    except Exception as e:
        print(f"Error fetching Binance candle: {e}")
        return pd.DataFrame()