#!/usr/bin/env python3
"""
Create a demo user for testing
"""
from app import app, db, User
from werkzeug.security import generate_password_hash

def create_demo_user():
    with app.app_context():
        # Check if demo user already exists
        existing_user = User.query.filter_by(username='demo').first()
        if existing_user:
            print("Demo user already exists!")
            return
        
        # Create demo user
        demo_user = User(
            username='demo',
            email='demo@example.com',
            password_hash=generate_password_hash('demo123')
        )
        
        db.session.add(demo_user)
        db.session.commit()
        print("Demo user created successfully!")
        print("Username: demo")
        print("Password: demo123")

if __name__ == "__main__":
    create_demo_user() 