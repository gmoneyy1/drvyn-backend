#!/usr/bin/env python3
"""
Test script to check deployment issues
"""
import os
from app import app, db

def test_deployment():
    print("=== Deployment Test ===")
    
    # Check environment variables
    print("\n1. Environment Variables:")
    env_vars = [
        "FLASK_SECRET_KEY",
        "DATABASE_URL", 
        "OPENAI_API_KEY",
        "COHERE_API_KEY",
        "AI_PROVIDER",
        "PORT"
    ]
    
    for var in env_vars:
        value = os.getenv(var)
        if value:
            print(f"  ✅ {var}: {'*' * len(value)} (set)")
        else:
            print(f"  ❌ {var}: Not set")
    
    # Check database connection
    print("\n2. Database Connection:")
    try:
        with app.app_context():
            db.session.execute("SELECT 1")
            print("  ✅ Database connection successful")
    except Exception as e:
        print(f"  ❌ Database connection failed: {e}")
    
    # Check basic endpoints
    print("\n3. Basic Endpoints:")
    with app.test_client() as client:
        try:
            response = client.get('/')
            print(f"  ✅ Root endpoint: {response.status_code}")
        except Exception as e:
            print(f"  ❌ Root endpoint error: {e}")
        
        try:
            response = client.get('/health')
            print(f"  ✅ Health endpoint: {response.status_code}")
        except Exception as e:
            print(f"  ❌ Health endpoint error: {e}")

if __name__ == "__main__":
    test_deployment() 