import sys
sys.path.insert(0, '.')

print("="*70)
print("TESTING ML PREDICTION")
print("="*70)

try:
    from ML.live_predictor import CryptoBreakoutPredictor
    
    print("\n✅ Import successful")
    
    print("\nLoading ETH models...")
    predictor = CryptoBreakoutPredictor(model_dir=r'c:\Users\kahan\Desktop\Quant Trading Bot\Roostoo Quant Competition\Code\19-03-2026 Ver.4\ML Training\models\eth_models')
    
    print("✅ Models loaded")
    print(f"   Feature cols: {len(predictor.feature_cols)}")
    
    print("\nMaking prediction...")
    result = predictor.predict('ETH/USDT', timeframe='15m')
    
    print("✅ Prediction successful!")
    print(f"   Class: {result['predicted_class']}")
    print(f"   Confidence: {result['confidence']*100:.1f}%")
    print(f"   Price: ${result['price']:.2f}")
    
except Exception as e:
    print(f"❌ ERROR: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*70)
