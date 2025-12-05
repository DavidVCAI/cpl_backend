from fastapi import APIRouter, HTTPException, Depends
from typing import List
from datetime import datetime
from bson import ObjectId

from app.database import get_database
from app.models.user import UserCreate, UserResponse, User
from app.middleware.auth import get_current_user, CognitoUser

router = APIRouter()


@router.get("/me", response_model=dict)
async def get_current_user_profile(current_user: CognitoUser = Depends(get_current_user)):
    """
    Get current authenticated user's profile.
    This endpoint validates the JWT token and returns user info.
    Used for security demo - Scenario 1: JWT Authentication.
    """
    db = await get_database()

    # Try to find user by cognito_id (sub) first
    user = await db.users.find_one({"cognito_id": current_user.sub})

    if user:
        return {
            "id": str(user["_id"]),
            "cognito_id": current_user.sub,
            "email": current_user.email,
            "name": user.get("name", current_user.email),
            "stats": user.get("stats", {}),
            "created_at": user.get("created_at"),
            "message": "User found in database",
            "jwt_validated": True
        }
    else:
        # User authenticated via Cognito but not in MongoDB
        # This is still a successful JWT validation!
        return {
            "cognito_id": current_user.sub,
            "email": current_user.email,
            "email_verified": current_user.email_verified,
            "message": "JWT validated successfully - User authenticated via Cognito",
            "jwt_validated": True,
            "note": "User exists in Cognito but profile not yet created in database"
        }


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


def convert_objectids_to_strings(obj):
    """Recursively convert all ObjectIds to strings in a dict/list"""
    if isinstance(obj, ObjectId):
        return str(obj)
    elif isinstance(obj, dict):
        return {key: convert_objectids_to_strings(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_objectids_to_strings(item) for item in obj]
    else:
        return obj

@router.get("/{user_id}/collectibles", response_model=list)
async def get_user_collectibles(user_id: str):
    """Get all collectibles owned by user"""
    try:
        db = await get_database()

        from app.services.collectible_service import CollectibleService
        collectible_service = CollectibleService(db)

        inventory = await collectible_service.get_user_inventory(user_id)

        # Convert ALL ObjectIds to strings recursively
        inventory = convert_objectids_to_strings(inventory)

        return inventory
    except Exception as e:
        print(f"❌ Error in get_user_collectibles endpoint: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error fetching collectibles: {str(e)}")
