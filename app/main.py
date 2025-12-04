from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from datetime import datetime
import logging

from app.config import settings
from app.database import get_database, close_database
from app.routes import users, events, collectibles, transcription
from app.routes import auth  # New auth routes with Cognito
from app.websockets.manager import ConnectionManager
from app.services.collectible_service import CollectibleService
from app.middleware.rate_limiter import RateLimitMiddleware, rate_limiter
from app.middleware.auth import verify_websocket_token, CognitoUser
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bson import ObjectId

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# WebSocket Connection Manager
manager = ConnectionManager()

# Scheduler for background tasks
scheduler = AsyncIOScheduler()


# Lifespan context manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown events"""
    # Startup
    logger.info("🚀 Starting CityPulse Live API...")

    # Initialize database
    await get_database()
    logger.info("✅ Database connected")

    # Start background tasks
    scheduler.start()
    logger.info("✅ Scheduler started")

    # Schedule collectible drops (every 5 minutes)
    scheduler.add_job(
        drop_random_collectibles,
        'interval',
        seconds=settings.COLLECTIBLE_DROP_INTERVAL,
        id='collectible_dropper'
    )

    # Schedule expired collectibles cleanup (every minute)
    scheduler.add_job(
        cleanup_expired_collectibles,
        'interval',
        seconds=60,
        id='collectible_cleaner'
    )

    # Schedule rate limiter cleanup (every 30 minutes)
    scheduler.add_job(
        rate_limiter.cleanup_old_records,
        'interval',
        minutes=30,
        id='rate_limiter_cleaner'
    )
    logger.info("Rate limiter cleanup scheduled")

    yield

    # Shutdown
    logger.info("🛑 Shutting down CityPulse Live API...")
    scheduler.shutdown()
    await close_database()
    logger.info("✅ Database closed")


# Initialize FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.API_VERSION,
    description="Real-time civic engagement platform for Bogotá - MVP",
    lifespan=lifespan
)

# CORS Configuration
# Allow all origins for serverless deployment (Vercel)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins (required for Vercel serverless)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"]
)

# Add Rate Limiting Middleware for login endpoints
app.add_middleware(
    RateLimitMiddleware,
    protected_paths=["/api/auth/login", "/api/users/login"]
)

# Include routers
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])  # New secure auth
app.include_router(users.router, prefix="/api/users", tags=["Users (Legacy)"])
app.include_router(events.router, prefix="/api/events", tags=["Events"])
app.include_router(collectibles.router, prefix="/api/collectibles", tags=["Collectibles"])
app.include_router(transcription.router, prefix="/api/transcription", tags=["Transcription"])


# Root endpoint
@app.get("/")
async def root():
    return {
        "app": settings.APP_NAME,
        "version": settings.API_VERSION,
        "status": "running",
        "timestamp": datetime.now().isoformat()
    }


# Health check
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "database": "connected",
        "instance_id": settings.INSTANCE_ID,
        "websocket_stats": await manager.get_stats(),
        "timestamp": datetime.now().isoformat()
    }


# Get all active user locations
@app.get("/api/locations")
async def get_all_locations():
    """Get all active user locations"""
    locations = await manager.get_all_locations()
    
    return {
        "locations": [
            {
                "user_id": user_id,
                "coordinates": list(loc.coordinates),
                "timestamp": loc.timestamp.isoformat(),
                "accuracy": loc.accuracy,
                "speed": loc.speed,
                "heading": loc.heading
            }
            for user_id, loc in locations.items()
        ],
        "total": len(locations),
        "timestamp": datetime.now().isoformat()
    }


# ========================================
# WebSocket Endpoints
# ========================================

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    user_id: str,
    token: str = Query(None, description="JWT access token for authentication")
):
    """
    Main WebSocket endpoint for real-time communication.

    Security: Requires JWT token as query parameter.
    Example: ws://localhost:8000/ws/user123?token=eyJhbGciOiJSUz...

    Handles:
    - Location updates
    - Event updates
    - Collectible drops
    - Chat messages
    """
    # Validate JWT token if provided (Security Scenario 1)
    authenticated_user = None
    if token:
        try:
            authenticated_user = await verify_websocket_token(websocket, token)
            logger.info(f"WebSocket authenticated: {authenticated_user.email}")
        except Exception as e:
            logger.warning(f"WebSocket auth failed for user_id {user_id}: {e}")
            # Allow connection but mark as unauthenticated for backward compatibility
            # In strict mode, uncomment below to reject:
            # await websocket.close(code=4001, reason="Invalid token")
            # return

    await manager.connect(websocket, user_id)
    logger.info(f"User {user_id} connected via WebSocket (authenticated: {authenticated_user is not None})")

    try:
        while True:
            # Receive message from client
            data = await websocket.receive_json()
            message_type = data.get("type")

            if message_type == "location_update":
                await handle_location_update(user_id, data)

            elif message_type == "join_event":
                await handle_join_event(user_id, data)

            elif message_type == "leave_event":
                await handle_leave_event(user_id, data)

            elif message_type == "chat_message":
                await handle_chat_message(user_id, data)

            elif message_type == "claim_collectible":
                await handle_claim_collectible(user_id, data)

            else:
                logger.warning(f"Unknown message type: {message_type}")

    except WebSocketDisconnect:
        await manager.disconnect(user_id)
        logger.info(f"User {user_id} disconnected")

        # Notify others about disconnection
        await manager.broadcast({
            "type": "user_disconnected",
            "user_id": user_id,
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"WebSocket error for user {user_id}: {e}")
        await manager.disconnect(user_id)


# ========================================
# WebSocket Message Handlers
# ========================================

async def handle_location_update(user_id: str, data: dict):
    """Handle real-time location updates with data consistency"""
    coordinates = data.get("coordinates")  # [lng, lat]
    accuracy = data.get("accuracy")
    speed = data.get("speed")
    heading = data.get("heading")

    if not coordinates or len(coordinates) != 2:
        logger.warning(f"Invalid coordinates from {user_id}: {coordinates}")
        return

    try:
        # Validate coordinates
        lng, lat = coordinates
        if not (-180 <= lng <= 180 and -90 <= lat <= 90):
            logger.warning(f"Coordinates out of range from {user_id}: {coordinates}")
            return

        # Update in-memory location with race condition protection
        location = await manager.update_user_location(
            user_id, 
            tuple(coordinates),
            accuracy=accuracy,
            speed=speed,
            heading=heading
        )

        # Update user location in database (async, non-blocking)
        db = await get_database()
        try:
            result = await db.users.update_one(
                {"_id": ObjectId(user_id)},
                {
                    "$set": {
                        "current_location": {
                            "type": "Point",
                            "coordinates": coordinates
                        },
                        "updated_at": datetime.now()
                    }
                }
            )
            if result.matched_count == 0:
                logger.warning(f"User {user_id} not found in database for location update")
        except Exception as db_error:
            logger.error(f"Database error updating location for {user_id}: {db_error}")
            # Continue execution even if DB update fails

        # Broadcast location update to all connected users
        await manager.broadcast_location_update(user_id, location, exclude_user=False)

        # Find nearby events (within 5km)
        nearby_events = await db.events.find({
            "location": {
                "$near": {
                    "$geometry": {
                        "type": "Point",
                        "coordinates": coordinates
                    },
                    "$maxDistance": 5000  # 5km
                }
            },
            "status": "active"
        }).to_list(20)

        # Convert ObjectIds to strings
        for event in nearby_events:
            event["_id"] = str(event["_id"])
            event["creator_id"] = str(event["creator_id"])

        # Send nearby events to user
        await manager.send_personal_message(user_id, {
            "type": "nearby_events",
            "events": nearby_events,
            "timestamp": datetime.now().isoformat()
        })

        # Get nearby users
        nearby_users = await manager.get_nearby_users(tuple(coordinates), radius_km=5.0)
        
        # Send nearby users to user (excluding themselves)
        nearby_users = [u for u in nearby_users if u["user_id"] != user_id]
        await manager.send_personal_message(user_id, {
            "type": "nearby_users",
            "users": nearby_users,
            "timestamp": datetime.now().isoformat()
        })

    except Exception as e:
        logger.error(f"Error handling location update for {user_id}: {e}")
        await manager.send_personal_message(user_id, {
            "type": "error",
            "message": "Failed to update location",
            "timestamp": datetime.now().isoformat()
        })


async def handle_join_event(user_id: str, data: dict):
    """Handle user joining an event with race condition protection"""
    event_id = data.get("event_id")

    db = await get_database()

    # Update event participants
    await db.events.update_one(
        {"_id": ObjectId(event_id)},
        {
            "$push": {
                "participants": {
                    "user_id": user_id,
                    "joined_at": datetime.now(),
                    "is_active": True
                }
            },
            "$inc": {"room.current_participants": 1}
        }
    )

    # Update user stats
    await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$inc": {"stats.events_attended": 1}}
    )

    # Join event in connection manager with race condition protection
    await manager.join_event(user_id, event_id)

    # Broadcast to all users in event
    await manager.broadcast_to_event(event_id, {
        "type": "user_joined",
        "user_id": user_id,
        "event_id": event_id,
        "timestamp": datetime.now().isoformat()
    })


async def handle_leave_event(user_id: str, data: dict):
    """Handle user leaving an event with race condition protection"""
    event_id = data.get("event_id")

    db = await get_database()

    # Update event participants
    await db.events.update_one(
        {"_id": ObjectId(event_id)},
        {
            "$pull": {
                "participants": {"user_id": user_id}
            },
            "$inc": {"room.current_participants": -1}
        }
    )

    # Leave event in connection manager with race condition protection
    await manager.leave_event(user_id, event_id)

    # Broadcast to all users in event
    await manager.broadcast_to_event(event_id, {
        "type": "user_left",
        "user_id": user_id,
        "event_id": event_id,
        "timestamp": datetime.now().isoformat()
    })


async def handle_chat_message(user_id: str, data: dict):
    """Handle chat messages in event"""
    event_id = data.get("event_id")
    message = data.get("message")

    # Broadcast message to event participants
    await manager.broadcast_to_event(event_id, {
        "type": "chat_message",
        "user_id": user_id,
        "message": message,
        "timestamp": datetime.now().isoformat()
    })


async def handle_claim_collectible(user_id: str, data: dict):
    """Handle collectible claim attempt"""
    collectible_id = data.get("collectible_id")

    db = await get_database()
    collectible_service = CollectibleService(db)

    # Attempt to claim (race condition handled in service)
    result = await collectible_service.claim_collectible(collectible_id, user_id)

    # Send result to user
    await manager.send_personal_message(user_id, {
        "type": "claim_result",
        "result": result,
        "timestamp": datetime.now().isoformat()
    })

    # If successful, broadcast to event participants
    if result.get("success"):
        # Get the event_id from the collectible result
        event_id = result.get("collectible", {}).get("event_id")
        if event_id:
            await manager.broadcast_to_event(event_id, {
                "type": "collectible_claimed",
                "collectible_id": collectible_id,
                "winner_id": user_id,
                "winner_name": result.get("winner_name", "Otro usuario"),
                "timestamp": datetime.now().isoformat()
            })


# ========================================
# Background Tasks
# ========================================

async def drop_random_collectibles():
    """Background task to drop collectibles in active events"""
    logger.info("🎁 Dropping random collectibles...")

    db = await get_database()
    collectible_service = CollectibleService(db)

    # Find active events with participants
    active_events = await db.events.find({
        "status": "active",
        "room.current_participants": {"$gte": 3}  # At least 3 people
    }).to_list(100)

    for event in active_events:
        # Random chance to drop (50%)
        import random
        if random.random() < 0.5:
            # Drop collectible
            collectible = await collectible_service.drop_random_collectible(
                str(event["_id"]),
                event["location"]["coordinates"]
            )

            # Convert datetime objects to ISO strings for JSON serialization
            collectible_broadcast = {
                **collectible,
                "dropped_at": collectible["dropped_at"].isoformat() if isinstance(collectible.get("dropped_at"), datetime) else collectible.get("dropped_at"),
                "expires_at": collectible["expires_at"].isoformat() if isinstance(collectible.get("expires_at"), datetime) else collectible.get("expires_at"),
                "created_at": collectible["created_at"].isoformat() if isinstance(collectible.get("created_at"), datetime) else collectible.get("created_at"),
            }

            # Broadcast to all participants
            await manager.broadcast_to_event(str(event["_id"]), {
                "type": "collectible_drop",
                "collectible": collectible_broadcast,
                "expires_in": 30,  # seconds
                "timestamp": datetime.now().isoformat()
            })

            logger.info(f"✅ Dropped {collectible['type']} collectible in event {event['_id']}")


async def cleanup_expired_collectibles():
    """Background task to clean up expired collectibles"""
    db = await get_database()
    collectible_service = CollectibleService(db)

    expired_count = await collectible_service.expire_old_collectibles()

    if expired_count > 0:
        logger.info(f"🧹 Cleaned up {expired_count} expired collectibles")


# Para ejecutar el servidor, usar desde la terminal:
# uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
