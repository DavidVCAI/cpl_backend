from fastapi import APIRouter, HTTPException
from typing import List
from datetime import datetime
from bson import ObjectId
import logging

from app.database import get_database
from app.models.event import EventCreate, Event
from app.services.daily_service import DailyService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("", response_model=dict, status_code=201)
async def create_event(event_data: EventCreate):
    """
    Create a new event with Daily.co video room
    """
    db = await get_database()
    daily_service = DailyService()

    # Create Daily.co room
    room_name = f"citypulse-{ObjectId()}"

    try:
        room_info = await daily_service.create_room(room_name, max_participants=15)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create video room: {str(e)}")

    # Create event
    event = {
        "title": event_data.title,
        "description": event_data.description,
        "category": event_data.category,
        "creator_id": event_data.creator_id,
        "location": {
            "type": "Point",
            "coordinates": event_data.coordinates,
            "address": event_data.address,
            "city": "Bogotá"
        },
        "status": "active",
        "room": {
            "daily_room_name": room_info["room_name"],
            "daily_room_url": room_info["room_url"],
            "max_participants": 15,
            "current_participants": 0,
            "is_recording": False
        },
        "participants": [],
        "collectibles_dropped": [],
        "metadata": {
            "views": 0,
            "total_minutes": 0,
            "peak_participants": 0
        },
        "starts_at": datetime.now(),
        "ends_at": None,
        "created_at": datetime.now(),
        "updated_at": datetime.now()
    }

    result = await db.events.insert_one(event)
    event["_id"] = str(result.inserted_id)

    # Update user stats
    await db.users.update_one(
        {"_id": ObjectId(event_data.creator_id)},
        {"$inc": {"stats.events_created": 1}}
    )

    return {
        "id": str(result.inserted_id),
        "title": event["title"],
        "room_url": event["room"]["daily_room_url"],
        "message": "Event created successfully"
    }


@router.get("/nearby", response_model=list)
async def get_nearby_events(lng: float, lat: float, max_distance: int = 5000, status: str = None):
    """
    Get events near a location (uses MongoDB geospatial query)

    Args:
        lng: Longitude
        lat: Latitude
        max_distance: Maximum distance in meters (default 5km)
        status: Filter by status (active, ended, cancelled) - optional, returns all if not provided
    """
    db = await get_database()

    # Build query filter
    query_filter = {
        "location": {
            "$near": {
                "$geometry": {
                    "type": "Point",
                    "coordinates": [lng, lat]
                },
                "$maxDistance": max_distance
            }
        }
    }

    # Add status filter if provided
    if status:
        query_filter["status"] = status

    events = await db.events.find(query_filter).to_list(100)

    # Convert ObjectId to string and map _id to id
    for event in events:
        event["id"] = str(event["_id"])
        event["creator_id"] = str(event["creator_id"])
        del event["_id"]  # Remove _id field

    return events


@router.get("/{event_id}", response_model=dict)
async def get_event(event_id: str):
    """Get event by ID"""
    db = await get_database()

    try:
        event = await db.events.find_one({"_id": ObjectId(event_id)})
    except:
        raise HTTPException(status_code=400, detail="Invalid event ID")

    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    event["id"] = str(event["_id"])
    event["creator_id"] = str(event["creator_id"])
    del event["_id"]  # Remove _id field

    return event


@router.post("/{event_id}/join", response_model=dict)
async def join_event(event_id: str, user_id: str):
    """
    Join an event and get Daily.co meeting token
    """
    db = await get_database()

    try:
        event = await db.events.find_one({"_id": ObjectId(event_id)})
        user = await db.users.find_one({"_id": ObjectId(user_id)})
    except:
        raise HTTPException(status_code=400, detail="Invalid ID")

    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Check if user already joined
    already_joined = any(p["user_id"] == user_id for p in event.get("participants", []))

    if not already_joined:
        # Add participant to event
        current_count = event["room"]["current_participants"]
        new_count = current_count + 1

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
                "$set": {
                    "room.current_participants": new_count,
                    "metadata.peak_participants": max(new_count, event["metadata"]["peak_participants"]),
                    "updated_at": datetime.now()
                },
                "$inc": {
                    "metadata.views": 1
                }
            }
        )

        # Update user stats
        await db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$inc": {"stats.events_attended": 1}}
        )

    # Generate Daily.co meeting token
    daily_service = DailyService()

    try:
        token = await daily_service.create_meeting_token(
            room_name=event["room"]["daily_room_name"],
            user_id=user_id,
            username=user["name"],
            is_owner=(str(event["creator_id"]) == user_id)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create meeting token: {str(e)}")

    return {
        "event_id": event_id,
        "room_url": event["room"]["daily_room_url"],
        "token": token,
        "is_owner": (str(event["creator_id"]) == user_id)
    }


@router.post("/{event_id}/end", response_model=dict)
async def end_event(event_id: str, creator_id: str):
    """End an event and delete the Daily.co room"""
    db = await get_database()

    try:
        event = await db.events.find_one({"_id": ObjectId(event_id)})
    except:
        raise HTTPException(status_code=400, detail="Invalid event ID")

    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    if str(event["creator_id"]) != creator_id:
        raise HTTPException(status_code=403, detail="Only the creator can end the event")

    # Delete Daily.co room to save resources
    daily_service = DailyService()
    room_name = event.get("room", {}).get("daily_room_name")

    if room_name:
        try:
            await daily_service.delete_room(room_name)
            logger.info(f"✅ Deleted Daily.co room: {room_name}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to delete Daily.co room {room_name}: {str(e)}")
            # Continue even if room deletion fails

    # Calculate total duration in minutes
    now = datetime.now()
    starts_at = event.get("starts_at", now)
    duration_minutes = int((now - starts_at).total_seconds() / 60)

    # Update event status
    await db.events.update_one(
        {"_id": ObjectId(event_id)},
        {
            "$set": {
                "status": "ended",
                "ends_at": now,
                "updated_at": now,
                "metadata.total_minutes": duration_minutes
            }
        }
    )

    return {"message": "Event ended successfully"}
