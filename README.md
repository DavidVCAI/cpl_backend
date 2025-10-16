# CityPulse Live - Backend (MVP)

Real-time civic engagement platform for Bogotá - FastAPI Backend

## 🎯 MVP Features

This is a simplified MVP focusing on the core user stories:

1. **User Registration** - Phone + Name only (no JWT authentication yet)
2. **Geolocation** - Real-time location tracking with MongoDB geospatial queries
3. **Video Conferencing** - Daily.co integration for video rooms
4. **Collectibles** - Race condition handling for competitive claiming
5. **AI Transcription** - Deepgram real-time speech-to-text

## 🛠 Technology Stack

- **FastAPI** - Modern Python web framework
- **MongoDB** - NoSQL database with geospatial indexes
- **Motor** - Async MongoDB driver
- **WebSocket** - Real-time bidirectional communication
- **Daily.co** - Video conferencing SDK
- **Deepgram** - AI speech-to-text transcription
- **APScheduler** - Background task scheduling

## 📁 Project Structure

```
cpl_backend/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app + WebSocket endpoints
│   ├── config.py               # Environment configuration
│   ├── database.py             # MongoDB connection + indexes
│   │
│   ├── models/                 # Pydantic models
│   │   ├── user.py
│   │   ├── event.py
│   │   ├── collectible.py
│   │   └── transcription.py
│   │
│   ├── routes/                 # API endpoints
│   │   ├── users.py
│   │   ├── events.py
│   │   └── collectibles.py
│   │
│   ├── services/               # Business logic
│   │   ├── daily_service.py        # Daily.co integration
│   │   ├── deepgram_service.py     # Deepgram AI transcription
│   │   └── collectible_service.py  # Race condition handling
│   │
│   └── websockets/             # WebSocket management
│       └── manager.py
│
├── scripts/
│   └── init_database.py        # MongoDB initialization
│
├── requirements.txt
├── .env.example
└── README.md
```

## 🚀 Quick Start

### 1. Prerequisites

- Python 3.10+
- MongoDB Atlas account (or local MongoDB)
- Daily.co API key (optional for video features)
- Deepgram API key (optional for transcription)

### 2. Installation

```bash
# Clone the repository
git clone <repository-url>
cd cpl_backend

# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Environment Setup

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```env
# MongoDB (REQUIRED)
MONGODB_URL=mongodb+srv://citypulseliveuser:lVgUsxszRc5psDaa@citypulselive.wxxyyq7.mongodb.net/?retryWrites=true&w=majority&appName=citypulselive
DATABASE_NAME=citypulse_live

# Daily.co API (OPTIONAL - for video features)
DAILY_API_KEY=your_daily_api_key_here
DAILY_DOMAIN=your-domain.daily.co

# Deepgram API (OPTIONAL - for transcription)
DEEPGRAM_API_KEY=your_deepgram_api_key_here

# CORS Origins (Frontend URL)
CORS_ORIGINS=http://localhost:5173,http://localhost:3000
```

### 4. Initialize Database

Run the database initialization script to create collections and indexes:

```bash
python scripts/init_database.py
```

This creates:
- `users` collection with phone unique index + geospatial index
- `events` collection with geospatial index
- `collectibles` collection with race condition indexes
- `user_collectibles` collection
- `transcriptions` collection

### 5. Run Development Server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at:
- API: http://localhost:8000
- Docs: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 📡 API Endpoints

### Users

```http
POST /api/users/register
  Body: { "phone": "+573001234567", "name": "Juan Pérez" }
  Response: { "id": "...", "phone": "...", "name": "..." }

GET /api/users/{user_id}
  Response: User profile with stats

GET /api/users/{user_id}/collectibles
  Response: User's collectible inventory
```

### Events

```http
POST /api/events?creator_id={user_id}
  Body: {
    "title": "Concierto en la 93",
    "description": "...",
    "category": "entretenimiento",
    "coordinates": [-74.0721, 4.7110],
    "address": "Carrera 15 #93-50"
  }
  Response: { "id": "...", "room_url": "https://..." }

GET /api/events/nearby?lng=-74.0721&lat=4.7110&max_distance=5000
  Response: List of nearby active events (within 5km)

GET /api/events/{event_id}
  Response: Event details

POST /api/events/{event_id}/join?user_id={user_id}
  Response: { "room_url": "...", "token": "..." }

POST /api/events/{event_id}/end?creator_id={creator_id}
  Response: { "message": "Event ended" }
```

### Collectibles

```http
POST /api/collectibles/claim?collectible_id={id}&user_id={id}
  Response: { "success": true/false, "message": "..." }

GET /api/collectibles/active/{event_id}
  Response: List of active collectibles in event
```

## 🔌 WebSocket API

Connect to: `ws://localhost:8000/ws/{user_id}`

### Client → Server Messages

```javascript
// Update location
{
  "type": "location_update",
  "coordinates": [-74.0721, 4.7110]
}

// Join event
{
  "type": "join_event",
  "event_id": "..."
}

// Leave event
{
  "type": "leave_event",
  "event_id": "..."
}

// Send chat message
{
  "type": "chat_message",
  "event_id": "...",
  "message": "Hola!"
}

// Claim collectible
{
  "type": "claim_collectible",
  "collectible_id": "..."
}
```

### Server → Client Messages

```javascript
// Nearby events notification
{
  "type": "nearby_events",
  "events": [...],
  "timestamp": "..."
}

// User joined event
{
  "type": "user_joined",
  "user_id": "...",
  "event_id": "..."
}

// Collectible dropped
{
  "type": "collectible_drop",
  "collectible": {...},
  "expires_in": 30
}

// Claim result
{
  "type": "claim_result",
  "result": { "success": true, "message": "..." }
}
```

## 🔑 Key Features Implementation

### 1. Geolocation (MongoDB Geospatial Queries)

Uses MongoDB's `2dsphere` indexes for efficient location queries:

```python
# Find events within 5km
events = await db.events.find({
    "location": {
        "$near": {
            "$geometry": {
                "type": "Point",
                "coordinates": [lng, lat]
            },
            "$maxDistance": 5000  # meters
        }
    },
    "status": "active"
}).to_list(20)
```

**IMPORTANT**: Coordinates MUST be in `[longitude, latitude]` order!

### 2. Video Conferencing (Daily.co)

Creates a video room for each event:

```python
# Create room
room_info = await daily_service.create_room("citypulse-event-123")

# Generate user token
token = await daily_service.create_meeting_token(
    room_name="citypulse-event-123",
    user_id="user_id",
    username="Juan",
    is_owner=True
)
```

### 3. Race Condition Handling (Collectibles)

Uses MongoDB's atomic `findOneAndUpdate()` to ensure only ONE user can claim:

```python
result = await collectibles.find_one_and_update(
    filter={
        "_id": collectible_id,
        "claimed_by": None,        # MUST be unclaimed
        "is_active": True,         # MUST be active
        "expires_at": {"$gt": datetime.now()}
    },
    update={
        "$set": {
            "claimed_by": user_id,
            "is_active": False
        }
    },
    return_document=ReturnDocument.AFTER
)
```

### 4. AI Transcription (Deepgram)

Real-time speech-to-text streaming:

```python
deepgram_service = DeepgramService()
await deepgram_service.start_streaming(on_transcript_callback, language="es")
```

## 🔄 Background Tasks

Scheduled tasks run via APScheduler:

1. **Collectible Drops** - Every 5 minutes, randomly drop collectibles in active events
2. **Expired Cleanup** - Every minute, deactivate expired collectibles

## 🧪 Testing

```bash
# Install test dependencies
pip install pytest pytest-asyncio httpx

# Run tests
pytest

# Run with coverage
pytest --cov=app tests/
```

### Test WebSocket with wscat

```bash
# Install wscat globally
npm install -g wscat

# Connect
wscat -c ws://localhost:8000/ws/test-user-123

# Send location update
{"type": "location_update", "coordinates": [-74.0721, 4.7110]}
```

## 🚢 Deployment

### Option 1: Render.com (Recommended for free tier)

1. Create account at [render.com](https://render.com)
2. New Web Service → Connect repository
3. Build command: `pip install -r requirements.txt`
4. Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. Add environment variables from `.env`

### Option 2: Railway.app

1. Create account at [railway.app](https://railway.app)
2. New Project → Deploy from GitHub
3. Add environment variables
4. Auto-deploys on git push

## 📊 MongoDB Schema

### Users

```javascript
{
  "_id": ObjectId,
  "phone": "+573001234567",  // Unique
  "name": "Juan Pérez",
  "stats": {
    "events_created": 0,
    "events_attended": 0,
    "collectibles_count": 0
  },
  "current_location": {
    "type": "Point",
    "coordinates": [-74.0721, 4.7110]  // [lng, lat]
  }
}
```

### Events

```javascript
{
  "_id": ObjectId,
  "title": "Concierto en la 93",
  "category": "entretenimiento",
  "creator_id": ObjectId,
  "location": {
    "type": "Point",
    "coordinates": [-74.0721, 4.7110]
  },
  "room": {
    "daily_room_name": "citypulse-event-123",
    "daily_room_url": "https://...",
    "current_participants": 5
  },
  "status": "active"
}
```

## 🤝 Contributing

This is an MVP for a university project. Team members:

1. Fork the repository
2. Create feature branch: `git checkout -b feature/amazing-feature`
3. Commit changes: `git commit -m 'Add amazing feature'`
4. Push to branch: `git push origin feature/amazing-feature`
5. Open Pull Request

## 📝 License

MIT License - See LICENSE file for details

## 👥 Team

- Backend Team: [List team members]
- Frontend Team: [List team members]

## 🔗 Links

- Frontend Repository: [Link]
- MongoDB Atlas: https://cloud.mongodb.com
- Daily.co Dashboard: https://dashboard.daily.co
- Deepgram Console: https://console.deepgram.com