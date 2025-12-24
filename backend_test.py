import requests
import sys
import time
import json
from datetime import datetime

class CryptoDashboardTester:
    def __init__(self, base_url="http://localhost:8001"):
        self.base_url = base_url
        self.tests_run = 0
        self.tests_passed = 0

    def run_test(self, name, method, endpoint, expected_status, data=None, timeout=10):
        """Run a single API test"""
        url = f"{self.base_url}/{endpoint}"
        headers = {'Content-Type': 'application/json'}

        self.tests_run += 1
        print(f"\n🔍 Testing {name}...")
        print(f"   URL: {url}")
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=headers, timeout=timeout)
            elif method == 'POST':
                response = requests.post(url, json=data, headers=headers, timeout=timeout)

            success = response.status_code == expected_status
            if success:
                self.tests_passed += 1
                print(f"✅ Passed - Status: {response.status_code}")
                try:
                    response_data = response.json()
                    print(f"   Response: {json.dumps(response_data, indent=2)[:200]}...")
                    return True, response_data
                except:
                    print(f"   Response: {response.text[:200]}...")
                    return True, {}
            else:
                print(f"❌ Failed - Expected {expected_status}, got {response.status_code}")
                print(f"   Response: {response.text[:200]}...")
                return False, {}

        except requests.exceptions.Timeout:
            print(f"❌ Failed - Request timeout after {timeout}s")
            return False, {}
        except requests.exceptions.ConnectionError:
            print(f"❌ Failed - Connection error (server may not be running)")
            return False, {}
        except Exception as e:
            print(f"❌ Failed - Error: {str(e)}")
            return False, {}

    def test_health_endpoint(self):
        """Test the health endpoint"""
        success, response = self.run_test(
            "Health Check",
            "GET",
            "api/health",
            200
        )
        if success and 'status' in response:
            print(f"   Health Status: {response.get('status')}")
            print(f"   Warmup Progress: {response.get('warmup', 'N/A')}%")
        return success

    def test_websocket_availability(self):
        """Test if WebSocket endpoint is available (basic connectivity)"""
        # We can't easily test WebSocket in this simple test, but we can check if the endpoint exists
        # by trying to connect to it with requests (which will fail but give us info)
        print(f"\n🔍 Testing WebSocket Endpoint Availability...")
        ws_url = f"{self.base_url}/api/ws"
        print(f"   WebSocket URL: {ws_url.replace('http', 'ws')}")
        
        try:
            # This will fail but tells us if the endpoint exists
            response = requests.get(ws_url, timeout=5)
            # WebSocket endpoints typically return 426 Upgrade Required when accessed via HTTP
            if response.status_code == 426:
                print("✅ WebSocket endpoint is available (426 Upgrade Required)")
                self.tests_passed += 1
            else:
                print(f"⚠️  WebSocket endpoint returned unexpected status: {response.status_code}")
        except Exception as e:
            print(f"⚠️  WebSocket endpoint check failed: {str(e)}")
        
        self.tests_run += 1

def main():
    print("🚀 Starting Crypto Dashboard Backend API Tests")
    print("=" * 50)
    
    # Setup
    tester = CryptoDashboardTester("http://localhost:8001")
    
    # Run tests
    print("\n📊 Testing Backend API Endpoints...")
    
    # Test health endpoint
    health_success = tester.test_health_endpoint()
    
    # Test WebSocket availability
    tester.test_websocket_availability()
    
    # Print results
    print("\n" + "=" * 50)
    print(f"📊 Test Results: {tester.tests_passed}/{tester.tests_run} tests passed")
    
    if tester.tests_passed == tester.tests_run:
        print("✅ All backend tests passed!")
        return 0
    else:
        print("❌ Some backend tests failed!")
        if not health_success:
            print("⚠️  Critical: Health endpoint failed - backend may not be running")
        return 1

if __name__ == "__main__":
    sys.exit(main())