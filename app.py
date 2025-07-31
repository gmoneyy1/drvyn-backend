from flask import Flask, render_template, request, jsonify, session, send_from_directory, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import openai
import cohere
from uuid import uuid4
import os
import json
from datetime import datetime, timezone, timedelta
import pytz
from functools import wraps
import logging

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv("FLASK_SECRET_KEY", str(uuid4()))
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///drvyn.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Enable CORS
CORS(app, supports_credentials=True, origins=[
    "http://localhost:8080", 
    "http://localhost:5173", 
    "http://localhost:3000",
    "https://your-frontend-domain.vercel.app",  # Replace with your actual Vercel domain
    "https://drvyn-daily-dashboard.vercel.app"  # Common Vercel domain pattern
])

# Configure AI providers
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
COHERE_API_KEY = os.getenv("COHERE_API_KEY")
AI_PROVIDER = os.getenv("AI_PROVIDER", "cohere")

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Database Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    timezone = db.Column(db.String(50), default='UTC')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    events = db.relationship('Event', backref='user', lazy=True)
    conversations = db.relationship('Conversation', backref='user', lazy=True)

class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Conversation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# Rate limiting
from collections import defaultdict
import time
request_counts = defaultdict(list)

def rate_limit(max_requests=20, window=60):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if current_user.is_authenticated:
                user_id = current_user.id
            else:
                user_id = request.remote_addr
            
            now = time.time()
            user_requests = request_counts[user_id]
            user_requests[:] = [req_time for req_time in user_requests if now - req_time < window]
            
            if len(user_requests) >= max_requests:
                return jsonify({"error": "Rate limit exceeded"}), 429
            
            user_requests.append(now)
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# Clear rate limit cache on startup
def clear_rate_limits():
    global request_counts
    request_counts.clear()
    print("Rate limits cleared")

# Routes
@app.route("/")
def index():
    return jsonify({"message": "Drvyn API is running", "status": "ok"})

@app.route("/test")
def test():
    return jsonify({"message": "Test endpoint working", "cors": "enabled"})

@app.route("/login", methods=['GET', 'POST'])
def login():
    print(f"Login request - Method: {request.method}")
    print(f"Request headers: {dict(request.headers)}")
    
    if request.method == 'POST':
        try:
            data = request.get_json()
            print(f"Login data: {data}")
            
            username = data.get('username')
            password = data.get('password')
            
            print(f"Attempting login for user: {username}")
            
            user = User.query.filter_by(username=username).first()
            if user and check_password_hash(user.password_hash, password):
                login_user(user)
                print(f"Login successful for user: {username}")
                return jsonify({"success": True, "redirect": "/app"})
            else:
                print(f"Login failed for user: {username}")
                return jsonify({"success": False, "error": "Invalid credentials"}), 401
        except Exception as e:
            print(f"Login error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    
    return jsonify({"message": "Login endpoint", "method": "POST"})

@app.route("/register", methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        try:
            data = request.get_json()
            print(f"Registration attempt - Data: {data}")
            
            username = data.get('username')
            email = data.get('email')
            password = data.get('password')
            
            print(f"Username: {username}, Email: {email}")
            
            if User.query.filter_by(username=username).first():
                print(f"Username {username} already exists")
                return jsonify({"success": False, "error": "Username already exists"}), 400
            
            if User.query.filter_by(email=email).first():
                print(f"Email {email} already exists")
                return jsonify({"success": False, "error": "Email already exists"}), 400
            
            user = User(
                username=username,
                email=email,
                password_hash=generate_password_hash(password)
            )
            db.session.add(user)
            db.session.commit()
            
            print(f"User {username} created successfully")
            login_user(user)
            return jsonify({"success": True, "redirect": "/app"})
        except Exception as e:
            print(f"Registration error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    
    return jsonify({"message": "Register endpoint", "method": "POST"})

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return jsonify({"success": True, "message": "Logged out successfully"})

@app.route("/app")
@login_required
def app_route():
    return jsonify({"message": "App endpoint", "user": current_user.username})

# API Routes
@app.route("/api/events", methods=['GET'])
@login_required
# @rate_limit(max_requests=100, window=60)  # Temporarily disabled for testing
def get_events():
    try:
        events = Event.query.filter_by(user_id=current_user.id).all()
        return jsonify({
            "events": [{
                "id": event.id,
                "title": event.title,
                "start": event.start_time.isoformat(),
                "end": event.end_time.isoformat()
            } for event in events]
        })
    except Exception as e:
        app.logger.error(f"Error fetching events: {e}")
        return jsonify({"error": "Failed to fetch events"}), 500

@app.route("/api/events", methods=['POST'])
@login_required
@rate_limit(max_requests=20, window=60)
def create_event():
    try:
        data = request.get_json()
        
        # Clean up date strings - remove extra spaces and fix format
        start_str = data['start'].replace(' ', '')
        end_str = data['end'].replace(' ', '')
        
        # Fix missing T separator in ISO format
        if 'T' not in start_str and len(start_str) >= 10:
            start_str = start_str[:10] + 'T' + start_str[10:]
        if 'T' not in end_str and len(end_str) >= 10:
            end_str = end_str[:10] + 'T' + end_str[10:]
        
        event = Event(
            title=data['title'],
            start_time=datetime.fromisoformat(start_str),
            end_time=datetime.fromisoformat(end_str),
            user_id=current_user.id
        )
        db.session.add(event)
        db.session.commit()
        
        return jsonify({
            "success": True,
            "event": {
                "id": event.id,
                "title": event.title,
                "start": event.start_time.isoformat(),
                "end": event.end_time.isoformat()
            }
        })
    except Exception as e:
        app.logger.error(f"Error creating event: {e}")
        return jsonify({"error": "Failed to create event"}), 500

@app.route("/api/events/<int:event_id>", methods=['DELETE'])
@login_required
@rate_limit(max_requests=20, window=60)
def delete_event(event_id):
    try:
        event = Event.query.filter_by(id=event_id, user_id=current_user.id).first()
        if not event:
            return jsonify({"error": "Event not found"}), 404
        
        db.session.delete(event)
        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        app.logger.error(f"Error deleting event: {e}")
        return jsonify({"error": "Failed to delete event"}), 500

@app.route("/api/user", methods=['GET'])
@login_required
def get_user():
    try:
        return jsonify({
            "id": current_user.id,
            "username": current_user.username,
            "email": current_user.email,
            "timezone": current_user.timezone
        })
    except Exception as e:
        app.logger.error(f"Error fetching user: {e}")
        return jsonify({"error": "Failed to fetch user data"}), 500

@app.route("/api/user/timezone", methods=['PUT'])
@login_required
@rate_limit(max_requests=10, window=60)
def update_user_timezone():
    try:
        data = request.get_json()
        timezone = data.get('timezone')
        
        if not timezone:
            return jsonify({"error": "Timezone is required"}), 400
        
        current_user.timezone = timezone
        db.session.commit()
        
        return jsonify({"success": True})
    except Exception as e:
        app.logger.error(f"Error updating timezone: {e}")
        return jsonify({"error": "Failed to update timezone"}), 500

@app.route("/api/events/<int:event_id>", methods=['PUT'])
@login_required
@rate_limit(max_requests=20, window=60)
def update_event(event_id):
    try:
        event = Event.query.filter_by(id=event_id, user_id=current_user.id).first()
        if not event:
            return jsonify({"error": "Event not found"}), 404
        
        data = request.get_json()
        event.title = data.get('title', event.title)
        event.start_time = datetime.fromisoformat(data.get('start'))
        event.end_time = datetime.fromisoformat(data.get('end'))
        event.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            "success": True,
            "event": {
                "id": event.id,
                "title": event.title,
                "start": event.start_time.isoformat(),
                "end": event.end_time.isoformat()
            }
        })
    except Exception as e:
        app.logger.error(f"Error updating event: {e}")
        return jsonify({"error": "Failed to update event"}), 500

# AI Chat with conversation persistence
@app.route("/ai", methods=["POST"])
@login_required
# @rate_limit(max_requests=100, window=60)  # Temporarily disabled for testing
def ai():
    try:
        user_input = request.json.get("input")
        if not user_input:
            return jsonify({"error": "No input provided"}), 400

        # Save user message
        user_conversation = Conversation(
            user_id=current_user.id,
            role='user',
            content=user_input
        )
        db.session.add(user_conversation)
        db.session.commit()

        # Get conversation history (last 5 messages for speed)
        recent_conversations = Conversation.query.filter_by(user_id=current_user.id)\
            .order_by(Conversation.timestamp.desc()).limit(5).all()
        recent_conversations.reverse()

        # Build conversation context
        messages = [{"role": "system", "content": get_ai_prompt()}]
        
        # Add user's timezone context
        user_tz = pytz.timezone(current_user.timezone or 'UTC')
        current_time = datetime.now(user_tz).strftime("%Y-%m-%d %H:%M:%S %Z")
        
        # Get user's events for context (limit to recent events for speed)
        user_events = Event.query.filter_by(user_id=current_user.id)\
            .filter(Event.start_time >= datetime.now() - timedelta(days=7))\
            .order_by(Event.start_time.desc()).limit(10).all()
        event_summary = " | ".join([
            f"{event.title} from {event.start_time.strftime('%Y-%m-%d %H:%M')} to {event.end_time.strftime('%H:%M')}"
            for event in user_events
        ]) if user_events else "None"

        # Add context message
        context_message = f"Current time: {current_time}. User's timezone: {current_user.timezone}. Current events: {event_summary}"
        messages.append({"role": "user", "content": context_message})
        
        # Add conversation history
        for conv in recent_conversations:
            messages.append({"role": conv.role, "content": conv.content})

        # Check AI provider and call appropriate service
        if AI_PROVIDER == "openai":
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key or api_key == "your-openai-api-key-here":
                assistant_msg = "I'm sorry, but the OpenAI API key is not configured. Please set up your OpenAI API key in the .env file."
            else:
                try:
                    client = openai.OpenAI(api_key=api_key)
                    response = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=messages,
                        temperature=0.7,
                        max_tokens=1000,
                        top_p=0.95,
                    )
                    assistant_msg = response.choices[0].message.content.strip()
                except Exception as e:
                    assistant_msg = f"I'm sorry, but there was an error with the OpenAI service: {str(e)}"
        
        elif AI_PROVIDER == "cohere":
            api_key = os.getenv("COHERE_API_KEY")
            if not api_key or api_key == "your-cohere-api-key-here":
                assistant_msg = "I'm sorry, but the Cohere API key is not configured. Please set up your Cohere API key in the .env file."
            else:
                try:
                    co = cohere.Client(api_key)
                    
                    # Build the full prompt with system message and conversation history
                    full_prompt = f"{get_ai_prompt()}\n\n"
                    
                    # Add conversation history
                    for msg in messages[1:]:  # Skip the system message
                        if msg["role"] == "user":
                            full_prompt += f"User: {msg['content']}\n"
                        elif msg["role"] == "assistant":
                            full_prompt += f"Assistant: {msg['content']}\n"
                    
                    full_prompt += f"User: {user_input}\nAssistant: Respond with ONLY valid JSON array. For scheduling requests, ALWAYS include an ADD command."
                    
                    response = co.generate(
                        prompt=full_prompt,
                        max_tokens=500,
                        temperature=0.7,
                        k=0,
                        p=0.95,
                        frequency_penalty=0,
                        presence_penalty=0
                    )
                    assistant_msg = response.generations[0].text.strip()
                except Exception as e:
                    assistant_msg = f"I'm sorry, but there was an error with the Cohere service: {str(e)}"
        
        else:
            assistant_msg = "I'm sorry, but no AI provider is configured. Please set up either OpenAI or Cohere API key in the .env file."

        # Save assistant response
        assistant_conversation = Conversation(
            user_id=current_user.id,
            role='assistant',
            content=assistant_msg
        )
        db.session.add(assistant_conversation)
        db.session.commit()

        # Parse commands - more robust parsing
        parsed_commands = []
        try:
            # Try to extract JSON from the response
            import re
            json_match = re.search(r'\[.*\]', assistant_msg, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
                parsed_commands = json.loads(json_str)
                if not isinstance(parsed_commands, list):
                    parsed_commands = [{"command": "MESSAGE", "text": assistant_msg}]
            else:
                # If no JSON found, treat as a simple message
                parsed_commands = [{"command": "MESSAGE", "text": assistant_msg}]
        except (json.JSONDecodeError, Exception) as e:
            app.logger.warning(f"Failed to parse AI response as JSON: {e}")
            # Fallback to treating the entire response as a message
            parsed_commands = [{"command": "MESSAGE", "text": assistant_msg}]
        
        # Fix date formats in commands
        for command in parsed_commands:
            if command.get('start') and isinstance(command['start'], str):
                # Fix space instead of T in dates and remove double T
                command['start'] = command['start'].replace(' ', 'T').replace('TT', 'T')
            if command.get('end') and isinstance(command['end'], str):
                # Fix space instead of T in dates and remove double T
                command['end'] = command['end'].replace(' ', 'T').replace('TT', 'T')

        return jsonify({"commands": parsed_commands})

    except Exception as e:
        app.logger.error(f"Error in AI chat: {e}")
        return jsonify({"error": "Failed to process request"}), 500

def get_ai_prompt():
    return """
You are Drvyn, a helpful productivity assistant. You can schedule tasks and events for users.

IMPORTANT: You MUST ALWAYS respond with ONLY a valid JSON array. No other text.

For scheduling requests, use this exact format:
[
    {
        "command": "ADD",
        "start": "2025-07-30T10:00:00",
        "end": "2025-07-30T11:00:00",
        "title": "Task Name"
    },
    {
        "command": "MESSAGE", 
        "text": "I've scheduled your task for tomorrow at 10 AM."
    }
]

ALWAYS include a MESSAGE command after scheduling to confirm what you did.

Scheduling rules:
- "today" = current date
- "tomorrow" = next day
- "later today" = 2-3 hours from now
- "this afternoon" = 2-5 PM today
- "this evening" = 6-9 PM today
- Default duration: 1 hour
- Default time: 9 AM if not specified
- Use ISO format: YYYY-MM-DDTHH:MM:SS (MUST use T as separator, no spaces)

For non-scheduling questions, respond with:
[
    {
        "command": "MESSAGE",
        "text": "Your helpful response here"
    }
]

Commands: ADD (schedule), REMOVE (delete), MESSAGE (respond)
"""

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    clear_rate_limits()
    app.run(debug=True, port=8000, host='0.0.0.0') 