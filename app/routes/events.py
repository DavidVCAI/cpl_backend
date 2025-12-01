from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional
from datetime import datetime, timezone
from bson import ObjectId
import logging

from app.database import get_database
from app.models.event import EventCreate, Event
from app.services.daily_service import DailyService
from app.middleware.auth import get_current_user, CognitoUser, get_current_user_optional
from app.middleware.room_authorization import (
    authorize_room_join,
    authorize_room_action,
    RoomPermission,
    get_user_room_role
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("", response_model=dict, status_code=201)
async def create_event(
    event_data: EventCreate,
    current_user: CognitoUser = Depends(get_current_user)
):
    """
    Create a new event with Daily.co video room.

    Requires JWT authentication.
    """
    db = await get_database()
    daily_service = DailyService()

    # Get MongoDB user by Cognito sub
    mongo_user = await db.users.find_one({"cognito_sub": current_user.sub})
    if not mongo_user:
        raise HTTPException(status_code=404, detail="User profile not found")

    creator_id = str(mongo_user["_id"])

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
        "creator_id": mongo_user["_id"],  # Use MongoDB ObjectId
        "creator_cognito_sub": current_user.sub,  # Store Cognito sub for reference
        "location": {
            "type": "Point",
            "coordinates": event_data.coordinates,
            "address": event_data.address,
            "city": "Bogotá"
        },
        "status": "active",
        "is_private": event_data.is_private if hasattr(event_data, 'is_private') else False,
        "moderators": [],  # For room authorization
        "banned_users": [],  # For room authorization
        "invited_users": [],  # For private events
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
        "starts_at": datetime.now(timezone.utc),
        "ends_at": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc)
    }

    result = await db.events.insert_one(event)
    event["_id"] = str(result.inserted_id)

    # Update user stats
    await db.users.update_one(
        {"_id": mongo_user["_id"]},
        {"$inc": {"stats.events_created": 1}}
    )

    logger.info(f"Event created: {result.inserted_id} by user {current_user.email}")

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
async def join_event(
    event_id: str,
    current_user: CognitoUser = Depends(get_current_user)
):
    """
    Join an event and get Daily.co meeting token.

    Security Scenario 2: Authorization for Video Room Access
    - Requires JWT authentication (validated by get_current_user)
    - Checks user is authorized to join this room (ACL/roles)
    - Returns 403 if not authorized
    - Target: 100% requests validated, decision < 150ms
    """
    db = await get_database()

    # Get MongoDB user by Cognito sub
    user = await db.users.find_one({"cognito_sub": current_user.sub})
    if not user:
        raise HTTPException(status_code=404, detail="User profile not found")

    user_id = str(user["_id"])

    try:
        event = await db.events.find_one({"_id": ObjectId(event_id)})
    except:
        raise HTTPException(status_code=400, detail="Invalid event ID")

    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    if event.get("status") != "active":
        raise HTTPException(status_code=400, detail="Event is not active")

    # Room Authorization Check (Scenario 2)
    role = await get_user_room_role(user_id, event_id, db)

    if role is None:
        logger.warning(f"Unauthorized room access: user={user_id}, event={event_id}")
        raise HTTPException(
            status_code=403,
            detail="Not authorized to join this room"
        )

    if role.value == "banned":
        raise HTTPException(
            status_code=403,
            detail="You have been banned from this event"
        )

    # Check if user already joined (defensive check)
    participants_list = event.get("participants", [])
    participant_ids = [p.get("user_id") for p in participants_list]
    already_joined = user_id in participant_ids

    logger.info(f"Join attempt - User: {user_id}, Event: {event_id}, Role: {role.value}, Already joined: {already_joined}")

    if not already_joined:
        # Atomic operation with filter to prevent duplicates
        result = await db.events.update_one(
            {
                "_id": ObjectId(event_id),
                "participants.user_id": {"$ne": user_id}
            },
            {
                "$push": {
                    "participants": {
                        "user_id": user_id,
                        "cognito_sub": current_user.sub,
                        "joined_at": datetime.now(timezone.utc),
                        "is_active": True,
                        "role": role.value
                    }
                },
                "$inc": {
                    "room.current_participants": 1,
                    "metadata.views": 1
                },
                "$set": {
                    "updated_at": datetime.now(timezone.utc)
                }
            }
        )

        logger.info(f"Join result - Modified: {result.modified_count}")

        if result.modified_count > 0:
            # Update peak_participants
            updated_event = await db.events.find_one({"_id": ObjectId(event_id)})
            if updated_event:
                current_count = updated_event["room"]["current_participants"]
                peak = updated_event["metadata"]["peak_participants"]
                if current_count > peak:
                    await db.events.update_one(
                        {"_id": ObjectId(event_id)},
                        {"$set": {"metadata.peak_participants": current_count}}
                    )

            # Update user stats
            await db.users.update_one(
                {"_id": user["_id"]},
                {"$inc": {"stats.events_attended": 1}}
            )

    # Generate Daily.co meeting token
    daily_service = DailyService()
    is_owner = str(event.get("creator_id")) == user_id

    try:
        token = await daily_service.create_meeting_token(
            room_name=event["room"]["daily_room_name"],
            user_id=user_id,
            username=user["name"],
            is_owner=is_owner
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create meeting token: {str(e)}")

    return {
        "event_id": event_id,
        "room_url": event["room"]["daily_room_url"],
        "token": token,
        "is_owner": is_owner,
        "role": role.value
    }


@router.post("/{event_id}/end", response_model=dict)
async def end_event(
    event_id: str,
    current_user: CognitoUser = Depends(get_current_user)
):
    """
    End an event and delete the Daily.co room.

    Requires JWT authentication and END_EVENT permission (creator only).
    """
    db = await get_database()

    # Get MongoDB user
    user = await db.users.find_one({"cognito_sub": current_user.sub})
    if not user:
        raise HTTPException(status_code=404, detail="User profile not found")

    user_id = str(user["_id"])

    try:
        event = await db.events.find_one({"_id": ObjectId(event_id)})
    except:
        raise HTTPException(status_code=400, detail="Invalid event ID")

    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    # Authorization: Only creator can end event
    if not await authorize_room_action(event_id, RoomPermission.END_EVENT, current_user):
        # Double-check with direct comparison
        if str(event["creator_id"]) != user_id:
            logger.warning(f"Unauthorized end event attempt: user={user_id}, event={event_id}")
            raise HTTPException(status_code=403, detail="Only the creator can end the event")

    # Delete Daily.co room to save resources
    daily_service = DailyService()
    room_name = event.get("room", {}).get("daily_room_name")

    if room_name:
        try:
            await daily_service.delete_room(room_name)
            logger.info(f"Deleted Daily.co room: {room_name}")
        except Exception as e:
            logger.warning(f"Failed to delete Daily.co room {room_name}: {str(e)}")

    # Calculate total duration in minutes
    now = datetime.now(timezone.utc)
    starts_at = event.get("starts_at", now)

    if starts_at.tzinfo is None:
        starts_at = starts_at.replace(tzinfo=timezone.utc)

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

    logger.info(f"Event ended: {event_id} by user {current_user.email}")

    return {"message": "Event ended successfully"}
