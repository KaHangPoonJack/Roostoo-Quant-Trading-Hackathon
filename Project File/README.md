Model: LightGBM + XGBoost Ensemble
Target Label: Two condition met(1. max price deviation, 2. during 3 hour window price dont reverse more than 0.5%)
multi-class
class 0, Move <1% (No trade)
class 1, Move 1%-3%
class 2, Move 3%-5%
class 3, Move >5%
Prediction Horizon: 12 bars (3hours)
Time frame: 15minute
Features: 
All the features you have mentioned, also is it more feature it will be more accurate?
i want to include SPX, USD index these macro features
Threshold: P > 0.7, if > 0.9 then bigger position size
Coin: 

If trade hold for more than 12 candles -> exit trade