"""
telegram_bot.py
===============
Telegram notification functions for trading bot
"""

import urllib.parse
import requests
from config.settings import TAKE_PROFIT_PCT, STOP_LOSS_PCT, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from datetime import datetime, timezone


def send_telegram_message(message: str):
    """Send a message to your Telegram chat via bot"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            'chat_id': TELEGRAM_CHAT_ID,
            'text': message,
            'parse_mode': 'HTML'  # Allows basic HTML formatting
        }
        
        response = requests.post(url, data=payload, timeout=10)
        if response.status_code != 200:
            print(f"⚠️ Telegram notification failed: {response.text}")
        else:
            print("✅ Telegram notification sent")
        return response.json()
    except Exception as e:
        print(f"⚠️ Error sending Telegram message: {e}")
        return None


def send_ml_prediction_message(prediction: dict):
    """
    Send ML prediction to Telegram with ALL class probabilities
    FIXED: Shows actual TP% from TAKE_PROFIT_PCT, not position_size_pct
    """
    try:
        probs = prediction['probabilities']
        predicted_class = prediction['predicted_class']

        # Get actual TP/SL % from settings (class-based)
        tp_pct = TAKE_PROFIT_PCT.get(predicted_class, 0.01) * 100
        sl_pct = STOP_LOSS_PCT.get(predicted_class, 0.015) * 100

        message = (
            f"🔮  <b>ML PREDICTION UPDATE</b>\n"
            f"├─ Symbol: {prediction['symbol']}\n"
            f"├─ Time: {prediction['timestamp'].strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
            f"├─ Price: ${prediction['price']:.2f}\n"
            f"├─ Predicted Class: {predicted_class}\n"
            f"├─ Confidence: {prediction['confidence']*100:.1f}%\n"
            f"├─ All Class Probabilities:\n"
            f"│   ├─ Class 0 (No Trade):     {probs[0]*100:6.2f}%\n"
            f"│   ├─ Class 1 (1-3%):         {probs[1]*100:6.2f}%\n"
            f"│   ├─ Class 2 (3-5%):         {probs[2]*100:6.2f}%\n"
            f"│   └─ Class 3 (>5%):          {probs[3]*100:6.2f}%\n"
            f"├─ Recommendation: {prediction['recommendation']}\n"
            f"├─ TP/SL Settings:\n"
            f"│   ├─ Stop Loss: {sl_pct:.2f}% (Class {predicted_class})\n"
            f"│   └─ Take Profit: {tp_pct:.1f}% (Class {predicted_class})\n"
            f"└─ Suggested Size: {prediction['position_size_pct']*100:.1f}%\n"
        )
        send_telegram_message(message)
    except Exception as e:
        print(f"Error sending ML prediction: {e}")


def send_tp_sl_update_message(symbol: str, entry_price: float,
                               current_price: float, tp_price: float,
                               sl_price: float, pl_pct: float,
                               predicted_class: int):
    """Send TP/SL status update to Telegram"""
    try:
        tp_distance = ((tp_price - current_price) / current_price) * 100
        sl_distance = ((current_price - sl_price) / current_price) * 100
        
        message = (
            f"📊  <b>TP/SL STATUS UPDATE</b>\n"
            f"├─ Symbol: {symbol}\n"
            f"├─ Entry Price: ${entry_price:.2f}\n"
            f"├─ Current Price: ${current_price:.2f}\n"
            f"├─ P&L: {pl_pct:+.2f}%\n"
            f"├─ Predicted Class: {predicted_class}\n"
            f"├─ Take Profit: ${tp_price:.2f} ({tp_distance:+.2f}% away)\n"
            f"├─ Stop Loss: ${sl_price:.2f} ({sl_distance:+.2f}% away)\n"
            f"└─ Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        )
        send_telegram_message(message)
    except Exception as e:
        print(f"Error sending TP/SL update: {e}")


def send_tp_triggered_message(symbol: str, entry_price: float,
                               exit_price: float, pl_pct: float,
                               predicted_class: int):
    """Send Take Profit triggered notification"""
    try:
        tp_target = TAKE_PROFIT_PCT.get(predicted_class, 0.01) * 100
        message = (
            f"✅  <b>TAKE PROFIT TRIGGERED</b>\n"
            f"├─ Symbol: {symbol}\n"
            f"├─ Entry Price: ${entry_price:.2f}\n"
            f"├─ Exit Price: ${exit_price:.2f}\n"
            f"├─ P&L: {pl_pct:+.2f}%\n"
            f"├─ TP Target: {tp_target:.1f}%\n"
            f"├─ Predicted Class: {predicted_class}\n"
            f"└─ Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        )
        send_telegram_message(message)
    except Exception as e:
        print(f"Error sending TP triggered message: {e}")


def send_sl_triggered_message(symbol: str, entry_price: float,
                               exit_price: float, pl_pct: float,
                               predicted_class: int):
    """Send Stop Loss triggered notification"""
    try:
        sl_limit = STOP_LOSS_PCT.get(predicted_class, 0.015) * 100
        message = (
            f"🛑  <b>STOP LOSS TRIGGERED</b>\n"
            f"├─ Symbol: {symbol}\n"
            f"├─ Entry Price: ${entry_price:.2f}\n"
            f"├─ Exit Price: ${exit_price:.2f}\n"
            f"├─ P&L: {pl_pct:+.2f}%\n"
            f"├─ SL Limit: {sl_limit:.2f}% (Class {predicted_class})\n"
            f"├─ Predicted Class: {predicted_class}\n"
            f"└─ Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        )
        send_telegram_message(message)
    except Exception as e:
        print(f"Error sending SL triggered message: {e}")


def send_trade_entry_message(symbol: str, side: str, entry_price: float,
                             predicted_class: int, probabilities: dict = None):
    """Send trade entry notification (ENTRY SIGNAL)"""
    try:
        probs_text = ""
        if probabilities:
            probs_text = (
                f"\n├─ ML Probabilities:\n"
                f"│  ├─ Class 0: {probabilities.get(0, 0)*100:.1f}%\n"
                f"│  ├─ Class 1: {probabilities.get(1, 0)*100:.1f}%\n"
                f"│  ├─ Class 2: {probabilities.get(2, 0)*100:.1f}%\n"
                f"│  └─ Class 3: {probabilities.get(3, 0)*100:.1f}%"
            )

        tp_pct = TAKE_PROFIT_PCT.get(predicted_class, 0.01) * 100
        sl_pct = STOP_LOSS_PCT.get(predicted_class, 0.015) * 100

        message = (
            f"🟢  <b>TRADE ENTRY</b>\n"
            f"├─ Symbol: {symbol}\n"
            f"├─ Side: {side}\n"
            f"├─ Entry Price: ${entry_price:.2f}\n"
            f"├─ Predicted Class: {predicted_class}\n"
            f"├─ TP Target: {tp_pct:.1f}%\n"
            f"├─ SL Limit: {sl_pct:.2f}%{probs_text}\n"
            f"└─ Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        )
        send_telegram_message(message)
    except Exception as e:
        print(f"Error sending trade entry message: {e}")


def send_trade_exit_message(symbol: str, side: str, entry_price: float,
                            exit_price: float, pnl_pct: float, reason: str,
                            predicted_class: int = None):
    """Send trade exit notification (EXIT SIGNAL)"""
    try:
        emoji = "✅" if pnl_pct >= 0 else "❌"
        
        message = (
            f"{emoji}  <b>TRADE EXIT</b>\n"
            f"├─ Symbol: {symbol}\n"
            f"├─ Side: {side}\n"
            f"├─ Entry Price: ${entry_price:.2f}\n"
            f"├─ Exit Price: ${exit_price:.2f}\n"
            f"├─ P&L: {pnl_pct:+.2f}%\n"
            f"├─ Reason: {reason}\n"
            f"├─ Predicted Class: {predicted_class or 'N/A'}\n"
            f"└─ Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        )
        send_telegram_message(message)
    except Exception as e:
        print(f"Error sending trade exit message: {e}")