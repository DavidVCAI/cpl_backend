from fastapi import APIRouter, HTTPException
from bson import ObjectId

from app.database import get_database
from app.services.collectible_service import CollectibleService

router = APIRouter()


@router.post("/claim", response_model=dict)
async def claim_collectible(collectible_id: str, user_id: str):
    """
    Attempt to claim a collectible (handles race condition)
    """
    db = await get_database()
    collectible_service = CollectibleService(db)

    result = await collectible_service.claim_collectible(collectible_id, user_id)

    return result


@router.get("/active/{event_id}", response_model=list)
async def get_active_collectibles(event_id: str):
    """Get all active (unclaimed) collectibles for an event"""
    db = await get_database()

    collectibles = await db.collectibles.find({
        "event_id": event_id,
        "is_active": True,
        "claimed_by": None
    }).to_list(50)

    for coll in collectibles:
        coll["_id"] = str(coll["_id"])

    return collectibles
