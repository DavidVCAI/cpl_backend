from fastapi import APIRouter, HTTPException
from bson import ObjectId

from app.database import get_database
from app.services.collectible_service import CollectibleService

router = APIRouter()


def fix_objectids(obj):
    if isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, list):
        return [fix_objectids(i) for i in obj]
    if isinstance(obj, dict):
        return {k: fix_objectids(v) for k, v in obj.items()}
    return obj

@router.post("/claim", response_model=dict)
async def claim_collectible(collectible_id: str, user_id: str):
    """
    Attempt to claim a collectible (handles race condition)
    """
    db = await get_database()
    collectible_service = CollectibleService(db)
    result = await collectible_service.claim_collectible(collectible_id, user_id)
    return fix_objectids(result)


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


@router.post("/generate", response_model=dict)
async def generate_collectible(event_id: str):
    """
    Generate a random collectible for a given event.
    - Random rarity (common, rare, epic, legendary)
    - Random name and image
    - Auto timestamps and expiration
    """
    db = await get_database()
    collectible_service = CollectibleService(db)

    # Llamar al método ya existente para crear uno aleatorio
    collectible = await collectible_service.drop_random_collectible(
        event_id=event_id,
        location=[-74.0817, 4.6097]
    )

    return {"success": True, "collectible": collectible}