#!/usr/bin/env python
"""Debug startup script to test if the app can start"""
import sys
import os

print(f"Python executable: {sys.executable}")
print(f"Python version: {sys.version}")
print(f"Working directory: {os.getcwd()}")
print(f"PORT env var: {os.environ.get('PORT', 'NOT SET')}")

try:
    import uvicorn
    print("✓ uvicorn imported successfully")
except ImportError as e:
    print(f"✗ Failed to import uvicorn: {e}")
    sys.exit(1)

try:
    from app.main import app
    print("✓ app.main imported successfully")
except Exception as e:
    print(f"✗ Failed to import app.main: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print(f"\nStarting server on port {os.environ.get('PORT', 7799)}...")
uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get('PORT', 7799)))