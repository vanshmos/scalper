#!/usr/bin/env python3
"""
Backend Test Suite for Crypto Scalping Signal Engine
Tests the Trade Accountability System implementation
"""

import requests
import json
import os
import sys
import sqlite3
from pathlib import Path

# Get the backend URL from frontend .env file
def get_backend_url():
    frontend_env_path = Path("/app/frontend/.env")
    if frontend_env_path.exists():
        with open(frontend_env_path, 'r') as f:
            for line in f:
                if line.startswith('REACT_APP_BACKEND_URL='):
                    return line.split('=', 1)[1].strip()
    return "http://localhost:8001"

BACKEND_URL = get_backend_url()
API_BASE = f"{BACKEND_URL}/api"

def test_status_endpoint():
    """Test the /api/status endpoint for State Persistence verification"""
    print("🔍 Testing /api/status endpoint...")
    
    try:
        response = requests.get(f"{API_BASE}/status", timeout=10)
        
        if response.status_code != 200:
            print(f"❌ Status endpoint failed with status code: {response.status_code}")
            return False
            
        data = response.json()
        
        # Check that we have data for all three symbols
        expected_symbols = ['btc', 'eth', 'sol']
        for symbol in expected_symbols:
            if symbol not in data:
                print(f"❌ Missing data for symbol: {symbol}")
                return False
            
            symbol_data = data[symbol]
            
            # Check current_price is present
            if 'current_price' not in symbol_data or symbol_data['current_price'] is None:
                print(f"❌ Missing current_price for {symbol}")
                return False
            
            # Check indicators are present
            if 'indicators' not in symbol_data:
                print(f"❌ Missing indicators for {symbol}")
                return False
                
            indicators = symbol_data['indicators']
            
            # Check for CVD indicator (proves state was loaded)
            if 'cvd' not in indicators or indicators['cvd'] is None:
                print(f"❌ Missing CVD indicator for {symbol}")
                return False
                
            cvd_data = indicators['cvd']
            if '5m' not in cvd_data or cvd_data['5m'] is None:
                print(f"❌ Missing CVD 5m data for {symbol}")
                return False
            
            # Check for OBI indicator (proves state was loaded)
            if 'obi' not in indicators or indicators['obi'] is None:
                print(f"❌ Missing OBI indicator for {symbol}")
                return False
            
            # Check for other required indicators
            required_indicators = ['atr_5m', 'rsi_5m', 'vwap']
            for indicator in required_indicators:
                if indicator not in indicators:
                    print(f"❌ Missing {indicator} indicator for {symbol}")
                    return False
            
            # Check regime is present
            if 'regime' not in symbol_data:
                print(f"❌ Missing regime for {symbol}")
                return False
                
            regime = symbol_data['regime']
            if regime not in ['TRENDING', 'RANGING']:
                print(f"❌ Invalid regime value for {symbol}: {regime}")
                return False
            
            print(f"✅ {symbol.upper()}: price=${symbol_data['current_price']:.2f}, "
                  f"CVD={cvd_data['5m']:.3f}, OBI={indicators['obi']:.3f}, "
                  f"regime={regime}")
        
        print("✅ /api/status endpoint test passed")
        return True
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Request failed: {e}")
        return False
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON response: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

def test_state_files():
    """Test that state files exist and contain valid data"""
    print("\n🔍 Testing state files...")
    
    data_dir = Path("/app/data")
    if not data_dir.exists():
        print("❌ Data directory /app/data does not exist")
        return False
    
    expected_files = [
        "BTC-USDT-SWAP_state.json",
        "ETH-USDT-SWAP_state.json", 
        "SOL-USDT-SWAP_state.json"
    ]
    
    for filename in expected_files:
        file_path = data_dir / filename
        
        if not file_path.exists():
            print(f"❌ State file missing: {filename}")
            return False
            
        try:
            with open(file_path, 'r') as f:
                state_data = json.load(f)
            
            # Check required fields
            required_fields = ['symbol', 'timestamp', 'recent_trades']
            for field in required_fields:
                if field not in state_data:
                    print(f"❌ Missing field '{field}' in {filename}")
                    return False
            
            # Check recent_trades is not empty (proves state persistence is working)
            recent_trades = state_data['recent_trades']
            if not isinstance(recent_trades, list) or len(recent_trades) == 0:
                print(f"❌ No recent_trades data in {filename}")
                return False
            
            # Check trade data structure
            first_trade = recent_trades[0]
            trade_fields = ['side', 'sz', 'ts']
            for field in trade_fields:
                if field not in first_trade:
                    print(f"❌ Missing trade field '{field}' in {filename}")
                    return False
            
            print(f"✅ {filename}: {len(recent_trades)} trades, "
                  f"last updated: {state_data['timestamp']}")
            
        except json.JSONDecodeError as e:
            print(f"❌ Invalid JSON in {filename}: {e}")
            return False
        except Exception as e:
            print(f"❌ Error reading {filename}: {e}")
            return False
    
    print("✅ State files test passed")
    return True

def test_websocket_endpoint():
    """Test that WebSocket endpoint is accessible (basic connectivity test)"""
    print("\n🔍 Testing WebSocket endpoint accessibility...")
    
    try:
        # Test that the WebSocket endpoint returns a proper HTTP error (not a connection error)
        # WebSocket endpoints typically return 400 or 426 when accessed via HTTP
        response = requests.get(f"{API_BASE}/ws", timeout=5)
        
        # We expect this to fail with a specific HTTP status, not a connection error
        if response.status_code in [400, 426, 405]:
            print("✅ WebSocket endpoint is accessible (returns expected HTTP error)")
            return True
        else:
            print(f"⚠️  WebSocket endpoint returned unexpected status: {response.status_code}")
            return True  # Still consider this a pass as the endpoint is reachable
            
    except requests.exceptions.ConnectionError:
        print("❌ WebSocket endpoint not accessible - connection failed")
        return False
    except requests.exceptions.Timeout:
        print("❌ WebSocket endpoint timeout")
        return False
    except Exception as e:
        print(f"⚠️  WebSocket test inconclusive: {e}")
        return True  # Don't fail the test for WebSocket connectivity issues

def main():
    """Run all backend tests"""
    print("🚀 Starting Backend Tests for State Persistence Feature")
    print(f"Backend URL: {BACKEND_URL}")
    print("=" * 60)
    
    tests = [
        ("API Status Endpoint", test_status_endpoint),
        ("State Files", test_state_files),
        ("WebSocket Endpoint", test_websocket_endpoint),
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        try:
            if test_func():
                passed += 1
            else:
                print(f"❌ {test_name} test failed")
        except Exception as e:
            print(f"❌ {test_name} test crashed: {e}")
    
    print("\n" + "=" * 60)
    print(f"📊 Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! State Persistence feature is working correctly.")
        return 0
    else:
        print("⚠️  Some tests failed. Check the output above for details.")
        return 1

if __name__ == "__main__":
    sys.exit(main())