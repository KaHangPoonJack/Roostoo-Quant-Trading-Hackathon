"""
ml_notification_bot.py
======================
Standalone ML prediction notification bot.
Sends Telegram alerts when breakout is predicted (Class 1, 2, or 3).
Checks ONLY when new 15-minute candle forms (:00, :15, :30, :45)
Displays ALL class probabilities in terminal and Telegram
"""

import time
from datetime import datetime, timezone
from pathlib import Path
import warnings
import os

# Suppress warnings
os.environ['LOKY_MAX_CPU_COUNT'] = '4'
warnings.filterwarnings('ignore', category=UserWarning)
warnings.filterwarnings('ignore', category=DeprecationWarning)

# Import from your existing project structure
from ML.live_predictor import CryptoBreakoutPredictor
from config.settings import ML_MODEL_DIR, ML_CONFIDENCE_THRESHOLD, ML_ENABLED
from core.telegram_bot import send_telegram_message
from core.utils import wait_until_next_quarter_hour


class MLNotificationBot:
    """
    Standalone bot that sends Telegram notifications for ML predictions.
    Only alerts when Class 1, 2, or 3 is predicted (breakout detected).
    Runs only at 15-minute candle formation (:00, :15, :30, :45)
    """
    
    def __init__(self, symbol='ETH/USDT', timeframe='15m', 
                 confidence_threshold=0.7):
        self.symbol = symbol
        self.timeframe = timeframe
        self.confidence_threshold = confidence_threshold
        
        # Initialize predictor
        print("=" * 70)
        print("🔮 ML NOTIFICATION BOT")
        print("=" * 70)
        print(f"📁 Model Directory: {ML_MODEL_DIR}")
        print(f"📊 Symbol: {symbol}")
        print(f"⏱️  Check Interval: Every 15 minutes (at :00, :15, :30, :45)")
        print(f"🎯 Confidence Threshold: {confidence_threshold*100:.1f}%")
        print()
        
        if not ML_ENABLED:
            print("⚠️  ML_ENABLED is False in settings.py - notifications disabled")
            self.predictor = None
            return
        
        try:
            self.predictor = CryptoBreakoutPredictor(model_dir=str(ML_MODEL_DIR))
            print("✅ ML Predictor loaded successfully")
            
            # Health check
            health = self.predictor.health_check()
            if health['ready']:
                print("✅ All systems ready")
            else:
                print("⚠️  Some checks failed:")
                for key, value in health.items():
                    if value is False:
                        print(f"   ❌ {key}")
        except Exception as e:
            print(f"❌ Failed to load predictor: {e}")
            self.predictor = None
    
    def _format_notification_message(self, result: dict) -> str:
        """Format prediction result for Telegram with ALL probabilities"""
        probs = result['probabilities']
        class_labels = {
            0: "No Trade (Consolidation)",
            1: "Small Breakout (1-3%)",
            2: "Medium Breakout (3-5%)",
            3: "Large Breakout (>5%)"
        }
        
        # Emoji based on class
        emojis = {0: "⚪", 1: "🟢", 2: "🟡", 3: "🔴"}
        emoji = emojis.get(result['predicted_class'], "⚪")
        
        message = (
            f"{emoji}  <b>ML BREAKOUT ALERT</b>\n"
            f"├─ Symbol: {result['symbol']}\n"
            f"├─ Time: {result['timestamp'].strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
            f"├─ Price: ${result['price']:.2f}\n"
            f"├─ Predicted Class: {result['predicted_class']}\n"
            f"├─ Signal: {class_labels.get(result['predicted_class'], 'Unknown')}\n"
            f"├─ Confidence: {result['confidence']*100:.1f}%\n"
            f"├─ All Class Probabilities:\n"
            f"│   ├─ Class 0 (No Trade):     {probs[0]*100:6.2f}%\n"
            f"│   ├─ Class 1 (1-3%):         {probs[1]*100:6.2f}%\n"
            f"│   ├─ Class 2 (3-5%):         {probs[2]*100:6.2f}%\n"
            f"│   └─ Class 3 (>5%):          {probs[3]*100:6.2f}%\n"
            f"├─ Recommendation: {result['recommendation']}\n"
            f"└─ Suggested Size: {result['position_size_pct']*100:.1f}%\n"
        )
        
        return message
    
    def _print_terminal_output(self, result: dict):
        """Print detailed prediction to terminal with ALL probabilities"""
        probs = result['probabilities']
        class_labels = {
            0: "No Trade (Consolidation)",
            1: "Small Breakout (1-3%)",
            2: "Medium Breakout (3-5%)",
            3: "Large Breakout (>5%)"
        }
        
        print("\n" + "=" * 70)
        print("🔮 ML PREDICTION RESULT")
        print("=" * 70)
        print(f"   Symbol:           {result['symbol']}")
        print(f"   Timestamp:        {result['timestamp'].strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"   Price:            ${result['price']:.2f}")
        print(f"   Predicted Class:  {result['predicted_class']}")
        print(f"   Signal:           {class_labels.get(result['predicted_class'], 'Unknown')}")
        print(f"   Confidence:       {result['confidence']*100:.2f}%")
        print()
        print("   📊 ALL CLASS PROBABILITIES:")
        print(f"      Class 0 (No Trade):     {probs[0]*100:6.2f}%  {'█' * int(probs[0]*10)}")
        print(f"      Class 1 (1-3%):         {probs[1]*100:6.2f}%  {'█' * int(probs[1]*10)}")
        print(f"      Class 2 (3-5%):         {probs[2]*100:6.2f}%  {'█' * int(probs[2]*10)}")
        print(f"      Class 3 (>5%):          {probs[3]*100:6.2f}%  {'█' * int(probs[3]*10)}")
        print()
        print(f"   Recommendation:   {result['recommendation']}")
        print(f"   Position Size:    {result['position_size_pct']*100:.2f}%")
        print(f"   Candle Age:       {result['data_freshness']['candle_age_seconds']:.1f} seconds")
        print("=" * 70)
    
    def check_and_notify(self):
        """Make prediction and send notification if breakout detected"""
        if self.predictor is None:
            print("⚠️  Predictor not initialized, skipping")
            return
        
        try:
            print(f"\n{'='*70}")
            current_time = datetime.now(timezone.utc)
            print(f"🔍 Checking prediction at {current_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
            
            # Get prediction
            result = self.predictor.predict(self.symbol, timeframe=self.timeframe)
            
            # Print detailed terminal output (ALWAYS, for all classes)
            self._print_terminal_output(result)
            
            predicted_class = result['predicted_class']
            confidence = result['confidence']
            
            # Only notify Telegram if Class 1, 2, or 3 (breakout detected)
            if predicted_class >= 1:
                # Check confidence threshold
                if confidence >= self.confidence_threshold:
                    message = self._format_notification_message(result)
                    print(f"📤 Sending Telegram notification...")
                    send_telegram_message(message)
                    print(f"✅ Telegram notification sent!")
                    
                    # Log to console
                    print(f"\n📊 BREAKOUT DETECTED:")
                    print(f"   Class: {predicted_class}")
                    print(f"   Confidence: {confidence*100:.2f}%")
                    print(f"   Threshold: {self.confidence_threshold*100:.1f}%")
                    print(f"   Position Size: {result['position_size_pct']*100:.2f}%")
                else:
                    print(f"⚠️  Breakout detected but confidence below threshold")
                    print(f"   Confidence: {confidence*100:.2f}% < {self.confidence_threshold*100:.1f}%")
                    print(f"   ❌ No Telegram notification sent")
            else:
                print(f"⚪ No breakout (Class 0 - Consolidation)")
                print(f"   ❌ No Telegram notification sent (Class 0)")
            
            return result
            
        except Exception as e:
            print(f"❌ Error during prediction: {e}")
            # Send error alert to Telegram
            error_message = (
                f"❌  <b>ML NOTIFICATION BOT ERROR</b>\n"
                f"├─ Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                f"├─ Error: {str(e)}\n"
                f"└─ Bot will continue running"
            )
            try:
                send_telegram_message(error_message)
            except:
                pass
            return None
    
    def run(self):
        """Run the notification bot continuously, checking at each 15min candle"""
        if self.predictor is None:
            print("❌ Cannot start - predictor not initialized")
            return
        
        print("\n" + "=" * 70)
        print("🚀 Starting ML Notification Bot")
        print("=" * 70)
        print(f"✅ Bot is running. Press Ctrl+C to stop.")
        print(f"📬 Telegram notifications: Class 1, 2, 3 only (confidence ≥ {self.confidence_threshold*100:.1f}%)")
        print(f"📊 Terminal output: All predictions (Class 0, 1, 2, 3)")
        print(f"⏱️  Checking at every 15-minute candle (:00, :15, :30, :45)")
        print()
        
        try:
            while True:
                # Wait until next 15-minute candle forms
                print(f"\n⏳ Waiting for next 15-minute candle...")
                wait_until_next_quarter_hour()
                
                # Small delay to ensure candle data is ready
                time.sleep(3)
                
                # Check and notify
                self.check_and_notify()
                
        except KeyboardInterrupt:
            print("\n\n⏹️  Bot stopped by user")
        except Exception as e:
            print(f"\n❌ Bot crashed: {e}")
            # Send crash alert
            try:
                error_message = (
                    f"🚨  <b>ML NOTIFICATION BOT CRASHED</b>\n"
                    f"├─ Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                    f"├─ Error: {str(e)}\n"
                    f"└─ Please restart the bot"
                )
                send_telegram_message(error_message)
            except:
                pass


# ================= RUN THE BOT =================
if __name__ == "__main__":
    # Create and run the bot
    bot = MLNotificationBot(
        symbol='ETH/USDT',
        timeframe='15m',
        confidence_threshold=0.7  # Only notify if confidence >= 70%
    )
    
    bot.run()