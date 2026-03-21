"""
daily_report.py
===============
Sends daily trading report via Telegram at UTC 00:00
Includes: Trading stats, ML predictions summary, P&L by coin, win rate
"""

import schedule
import time
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from core.telegram_bot import send_telegram_message
from core.trading_history import history_db


def get_daily_trading_summary(date: datetime):
    """Get trading summary for a specific date"""
    trades = history_db.get_trades_by_date(date)
    
    if not trades:
        return None
    
    # Overall stats
    total_trades = len(trades)
    wins = sum(1 for t in trades if t.get('pnl_pct', 0) > 0)
    losses = total_trades - wins
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
    total_pnl = sum(t.get('pnl_pct', 0) for t in trades)
    avg_pnl = total_pnl / total_trades if total_trades > 0 else 0
    best_trade = max(trades, key=lambda x: x.get('pnl_pct', 0)) if trades else None
    worst_trade = min(trades, key=lambda x: x.get('pnl_pct', 0)) if trades else None
    
    # By coin stats
    coin_stats = {}
    for trade in trades:
        symbol = trade['symbol']
        if symbol not in coin_stats:
            coin_stats[symbol] = {
                'trades': 0,
                'wins': 0,
                'losses': 0,
                'pnl': 0,
                'win_rate': 0
            }
        coin_stats[symbol]['trades'] += 1
        if trade.get('pnl_pct', 0) > 0:
            coin_stats[symbol]['wins'] += 1
        else:
            coin_stats[symbol]['losses'] += 1
        coin_stats[symbol]['pnl'] += trade.get('pnl_pct', 0)
    
    # Calculate win rate per coin
    for symbol in coin_stats:
        stats = coin_stats[symbol]
        stats['win_rate'] = (stats['wins'] / stats['trades'] * 100) if stats['trades'] > 0 else 0
    
    return {
        'date': date.strftime('%Y-%m-%d'),
        'summary': {
            'total_trades': total_trades,
            'wins': wins,
            'losses': losses,
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'avg_pnl': avg_pnl,
            'best_trade': {
                'symbol': best_trade['symbol'],
                'pnl': best_trade['pnl_pct']
            } if best_trade else None,
            'worst_trade': {
                'symbol': worst_trade['symbol'],
                'pnl': worst_trade['pnl_pct']
            } if worst_trade else None
        },
        'by_coin': coin_stats,
        'all_trades': trades  # Full trade history
    }


def get_daily_ml_summary(date: datetime):
    """Get ML prediction summary for a specific date"""
    predictions = history_db.get_daily_ml_summary(date)
    
    if not predictions:
        return None
    
    return {
        'date': date.strftime('%Y-%m-%d'),
        'by_coin': [
            {
                'symbol': p['symbol'],
                'total_predictions': p['total_predictions'],
                'avg_class': p['avg_class'],
                'avg_confidence': p['avg_confidence'],
                'avg_breakout_prob': p['avg_breakout_prob']
            }
            for p in predictions
        ]
    }


def get_all_ml_predictions_by_date(date: datetime):
    """Get all ML predictions for a specific date (every 15min)"""
    predictions = history_db.get_recent_ml_predictions(limit=1000)
    
    if not predictions:
        return None
    
    # Filter by date
    start_date = date.replace(hour=0, minute=0, second=0, microsecond=0)
    end_date = date.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    filtered = []
    for pred in predictions:
        ts = pred.get('timestamp')
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            except:
                continue
        
        if start_date <= ts <= end_date:
            filtered.append(pred)
    
    # Group by symbol
    by_symbol = {}
    for pred in filtered:
        symbol = pred['symbol']
        if symbol not in by_symbol:
            by_symbol[symbol] = []
        by_symbol[symbol].append(pred)
    
    return by_symbol


def format_daily_report(trading_summary, ml_summary):
    """Format daily report as Telegram message"""
    if not trading_summary:
        return "📊 <b>Daily Trading Report</b>\n└─ No trades today"
    
    s = trading_summary['summary']
    date = trading_summary['date']
    
    # Overall summary
    emoji = "✅" if s['win_rate'] >= 50 else "⚠️" if s['win_rate'] >= 30 else "❌"
    pnl_emoji = "📈" if s['total_pnl'] > 0 else "📉"
    
    message = f"{emoji} <b>DAILY TRADING REPORT</b>\n"
    message += f"├─ 📅 Date: {date}\n"
    message += f"├─ 📊 Total Trades: {s['total_trades']}\n"
    message += f"├─ 🎯 Win Rate: {s['win_rate']:.1f}% ({s['wins']}W/{s['losses']}L)\n"
    message += f"├─ {pnl_emoji} Total P&L: {s['total_pnl']:+.2f}%\n"
    message += f"├─ 📈 Avg P&L: {s['avg_pnl']:+.2f}%\n"
    
    if s['best_trade']:
        message += f"├─ ⭐ Best: {s['best_trade']['symbol']} ({s['best_trade']['pnl']:+.2f}%)\n"
    if s['worst_trade']:
        message += f"├─ 🔻 Worst: {s['worst_trade']['symbol']} ({s['worst_trade']['pnl']:+.2f}%)\n"
    
    # By coin breakdown
    message += f"\n📊 <b>BY COIN:</b>\n"
    for symbol, stats in sorted(s['by_coin'].items(), key=lambda x: x[1]['pnl'], reverse=True):
        coin_emoji = "✅" if stats['win_rate'] >= 50 else "⚠️" if stats['win_rate'] >= 30 else "❌"
        pnl_icon = "📈" if stats['pnl'] > 0 else "📉"
        message += f"├─ {coin_emoji} {symbol}: {stats['trades']} trades | {stats['win_rate']:.0f}% WR | {pnl_icon} {stats['pnl']:+.2f}%\n"
    
    # ML Summary
    if ml_summary and ml_summary.get('by_coin'):
        message += f"\n🔮 <b>ML PREDICTIONS SUMMARY:</b>\n"
        for ml in ml_summary['by_coin']:
            message += f"├─ {ml['symbol']}: {ml['total_predictions']} preds | "
            message += f"Conf: {ml['avg_confidence']*100:.1f}% | "
            message += f"Breakout: {ml['avg_breakout_prob']*100:.1f}%\n"
    
    message += f"\n⏰ Report generated at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
    
    return message


def format_full_trade_history(trades):
    """Format full trade history as CSV-like text"""
    if not trades:
        return "No trades executed"
    
    message = "📝 <b>FULL TRADE HISTORY</b>\n\n"
    message += "<code>"
    message += f"{'Symbol':<8} {'Side':<6} {'Entry Time':<20} {'Exit Time':<20} {'Entry $':<12} {'Exit $':<12} {'P&L %':<10} {'Class':<6}\n"
    message += "-" * 100 + "\n"
    
    for trade in trades:
        entry_time = trade.get('entry_time', 'N/A')
        if isinstance(entry_time, str):
            entry_time = entry_time[:19]  # Trim to YYYY-MM-DD HH:MM:SS
        
        exit_time = trade.get('exit_time', 'N/A')
        if isinstance(exit_time, str):
            exit_time = exit_time[:19]
        
        message += f"{trade['symbol']:<8} "
        message += f"{trade.get('side', 'N/A'):<6} "
        message += f"{entry_time:<20} "
        message += f"{exit_time:<20} "
        message += f"{trade.get('entry_price', 0):<12.2f} "
        message += f"{trade.get('exit_price', 0):<12.2f} "
        message += f"{trade.get('pnl_pct', 0):<+10.2f} "
        message += f"{trade.get('predicted_class', 'N/A'):<6}\n"
    
    message += "</code>"
    return message


def format_ml_prediction_history(ml_by_symbol):
    """Format ML prediction history by coin"""
    if not ml_by_symbol:
        return "No ML prediction data"
    
    message = "🔮 <b>ML PREDICTION HISTORY (Every 15min)</b>\n\n"
    
    for symbol, predictions in sorted(ml_by_symbol.items()):
        message += f"\n<b>{symbol}</b> - {len(predictions)} predictions\n"
        message += "<code>"
        message += f"{'Time':<20} {'Class':<6} {'Conf %':<8} {'Breakout %':<12} {'Recommendation':<20}\n"
        message += "-" * 70 + "\n"
        
        # Sort by timestamp
        sorted_preds = sorted(predictions, key=lambda x: x.get('timestamp', ''))
        
        for pred in sorted_preds:
            ts = pred.get('timestamp', 'N/A')
            if isinstance(ts, str):
                ts = ts[:19]  # Trim to YYYY-MM-DD HH:MM:SS
            
            message += f"{ts:<20} "
            message += f"{pred.get('predicted_class', 'N/A'):<6} "
            message += f"{(pred.get('confidence', 0) or 0)*100:<8.1f} "
            message += f"{(pred.get('breakout_prob', 0) or 0)*100:<12.1f} "
            message += f"{pred.get('recommendation', 'N/A'):<20}\n"
        
        message += "</code>\n"
    
    return message


def send_daily_report():
    """Send daily trading report via Telegram"""
    print(f"[{datetime.now(timezone.utc)}] Sending daily report...")
    
    # Get yesterday's data (report for completed day)
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    yesterday = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Get trading summary
    trading_summary = get_daily_trading_summary(yesterday)
    
    # Get ML summary
    ml_summary = get_daily_ml_summary(yesterday)
    
    # Get full ML prediction history
    ml_history = get_all_ml_predictions_by_date(yesterday)
    
    # 1. Send summary report
    message = format_daily_report(trading_summary, ml_summary)
    send_telegram_message(message)
    
    # 2. Send full trade history (if trades exist)
    if trading_summary and trading_summary.get('all_trades'):
        trade_history_msg = format_full_trade_history(trading_summary['all_trades'])
        # Split if too long
        if len(trade_history_msg) > 4000:
            trade_history_msg = trade_history_msg[:4000] + "\n... (truncated, check JSON export)"
        send_telegram_message(trade_history_msg)
    
    # 3. Send ML prediction history (if data exists)
    if ml_history:
        ml_history_msg = format_ml_prediction_history(ml_history)
        # Split into multiple messages if too long
        if len(ml_history_msg) > 4000:
            # Split by coin
            for symbol, predictions in sorted(ml_history.items()):
                coin_msg = format_ml_prediction_history({symbol: predictions})
                if len(coin_msg) > 4000:
                    coin_msg = coin_msg[:4000] + "\n... (truncated)"
                send_telegram_message(coin_msg)
        else:
            send_telegram_message(ml_history_msg)
    
    # 4. Send JSON data export (for parsing)
    if trading_summary:
        json_data = {
            'report_type': 'daily_trading_report',
            'date': trading_summary['date'],
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'summary': trading_summary['summary'],
            'by_coin': trading_summary['by_coin'],
            'all_trades': trading_summary['all_trades'],
            'ml_summary': ml_summary,
            'ml_history_by_coin': ml_history
        }
        
        # Send as formatted code block for easy parsing
        json_message = (
            f"<b>📄 DATA EXPORT (JSON)</b>\n"
            f"<code>{json.dumps(json_data, indent=2, default=str)}</code>"
        )
        
        # Split into multiple messages if too long (Telegram 4096 char limit)
        chunk_size = 4000
        chunks = [json_message[i:i+chunk_size] for i in range(0, len(json_message), chunk_size)]
        
        for i, chunk in enumerate(chunks):
            if i > 0:
                chunk = f"<code>... (continued)</code>\n{chunk}"
            if i == len(chunks) - 1:
                chunk += "\n<code>(end of export)</code>"
            send_telegram_message(chunk)
    
    print(f"[{datetime.now(timezone.utc)}] Daily report sent!")


def run_scheduler():
    """Run the daily report scheduler"""
    print("="*70)
    print("🕐 DAILY REPORT SCHEDULER STARTED")
    print("="*70)
    print(f"⏰ Reports will be sent daily at UTC 00:00")
    print(f"📊 Next report: {(datetime.now(timezone.utc) + timedelta(days=1)).replace(hour=0, minute=0, second=0).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("="*70)
    
    # Schedule daily report at UTC 00:00
    schedule.every().day.at("00:00").do(send_daily_report)
    
    # Run scheduler
    while True:
        schedule.run_pending()
        time.sleep(60)  # Check every minute


if __name__ == "__main__":
    # For testing: send report immediately
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        print("🧪 TEST MODE: Sending report for today...")
        send_daily_report()
    else:
        # Run scheduler
        run_scheduler()
