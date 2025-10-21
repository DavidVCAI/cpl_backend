from fastapi import APIRouter, HTTPException, Depends
from typing import List
from datetime import datetime
from bson import ObjectId

from app.database import get_database
from app.models.user import UserCreate, UserResponse, User

router = APIRouter()


@router.post("/register", response_model=dict, status_code=201)
async def register_user(user_data: UserCreate):
    """
    Register a new user (MVP: phone + name only)
    """
    db = await get_database()

    # Check if phone already exists
    existing_user = await db.users.find_one({"phone": user_data.phone})
    if existing_user:
        raise HTTPException(status_code=400, detail="Phone number already registered")

    # Create new user
    user = {
        "phone": user_data.phone,
        "name": user_data.name,
        "stats": {
            "events_created": 0,
            "events_attended": 0,
            "collectibles_count": 0,
            "total_video_minutes": 0
        },
        "current_location": None,
        "created_at": datetime.now(),
        "updated_at": datetime.now()
    }

    result = await db.users.insert_one(user)

    return {
        "id": str(result.inserted_id),
        "phone": user_data.phone,
        "name": user_data.name,
        "message": "User registered successfully"
    }


@router.get("/{user_id}", response_model=dict)
async def get_user(user_id: str):
    """Get user by ID"""
    db = await get_database()

    try:
        user = await db.users.find_one({"_id": ObjectId(user_id)})
    except:
        raise HTTPException(status_code=400, detail="Invalid user ID")

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "id": str(user["_id"]),
        "phone": user["phone"],
        "name": user["name"],
        "stats": user.get("stats", {}),
        "created_at": user["created_at"]
    }


@router.post("/login", response_model=dict)
async def login_user(user_data: UserCreate):
    """
    Login user by phone number (MVP: simple phone lookup)
    """
    db = await get_database()

    # Find user by phone
    user = await db.users.find_one({"phone": user_data.phone})

    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado. Por favor regístrate primero.")

    return {
        "id": str(user["_id"]),
        "phone": user["phone"],
        "name": user["name"],
        "stats": user.get("stats", {}),
        "created_at": user["created_at"],
        "message": "Login exitoso"
    }


@router.get("/{user_id}/collectibles", response_model=list)
async def get_user_collectibles(user_id: str):
    """Get all collectibles owned by user"""
    db = await get_database()

    from app.services.collectible_service import CollectibleService
    collectible_service = CollectibleService(db)

    inventory = await collectible_service.get_user_inventory(user_id)

    return inventory
