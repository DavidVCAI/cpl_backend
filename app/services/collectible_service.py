from pymongo import ReturnDocument
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from bson import ObjectId
import random


class CollectibleService:
    """Service for handling collectibles with race condition safety"""

    def __init__(self, db):
        self.db = db
        self.collectibles = db.collectibles
        self.user_collectibles = db.user_collectibles

    async def create_collectible(
            self,
            event_id: str,
            rarity: str = "common",
            drop_location: List[float] = None
    ) -> Dict:
        """
        Create a new collectible for an event

        Args:
            event_id: Event identifier
            rarity: common, rare, epic, legendary
            drop_location: [longitude, latitude]

        Returns:
            Created collectible document
        """
        rarity_config = {
            "common": {"score": 10, "name": "Bogotá Citizen"},
            "rare": {"score": 30, "name": "City Explorer"},
            "epic": {"score": 60, "name": "Urban Legend"},
            "legendary": {"score": 100, "name": "CityPulse Icon"}
        }

        config = rarity_config.get(rarity, rarity_config["common"])

        collectible = {
            "name": config["name"],
            "type": rarity,
            "rarity_score": config["score"],
            "image_url": f"/collectibles/{rarity}.svg",
            "description": f"Limited edition {rarity} collectible",
            "event_id": event_id,
            "dropped_at": datetime.now(),
            "expires_at": datetime.now() + timedelta(seconds=30),  # 30 sec to claim
            "claimed_by": None,
            "claimed_at": None,
            "drop_location": {
                "type": "Point",
                "coordinates": drop_location or [0, 0]
            },
            "is_active": True,
            "metadata": {
                "total_available": 1,  # Only ONE person can claim!
                "claim_attempts": 0,
                "successful_claims": 0
            },
            "created_at": datetime.now()
        }

        result = await self.collectibles.insert_one(collectible)
        collectible["_id"] = str(result.inserted_id)

        return collectible

    async def claim_collectible(
            self,
            collectible_id: str,
            user_id: str
    ) -> Dict:
        """
        Attempt to claim a collectible (RACE CONDITION SAFE!)

        This uses MongoDB's atomic findOneAndUpdate to ensure
        only ONE user can successfully claim the collectible,
        even if multiple users click at the exact same time.

        Args:
            collectible_id: Collectible identifier
            user_id: User attempting to claim

        Returns:
            Result with success status and message
        """
        try:
            coll_oid = ObjectId(collectible_id)

            print(f"🎯 Claim attempt - User: {user_id}, Collectible: {collectible_id}")

            # Increment attempt counter (for analytics)
            await self.collectibles.update_one(
                {"_id": coll_oid},
                {"$inc": {"metadata.claim_attempts": 1}}
            )

            # ATOMIC OPERATION - This is the key!
            # MongoDB will only update if ALL conditions match
            result = await self.collectibles.find_one_and_update(
                filter={
                    "_id": coll_oid,
                    "claimed_by": None,  # MUST be unclaimed
                    "is_active": True,  # MUST be active
                    "expires_at": {"$gt": datetime.now()}  # NOT expired
                },
                update={
                    "$set": {
                        "claimed_by": user_id,
                        "claimed_at": datetime.now(),
                        "is_active": False
                    },
                    "$inc": {
                        "metadata.successful_claims": 1
                    }
                },
                return_document=ReturnDocument.AFTER
            )

            if result is None:
                # Someone else claimed it first OR it expired
                collectible = await self.collectibles.find_one({"_id": coll_oid})

                if collectible and collectible["claimed_by"]:
                    print(f"❌ Already claimed by: {collectible['claimed_by']}")
                    return {
                        "success": False,
                        "message": "Someone else claimed it first!",
                        "claimed_by": str(collectible["claimed_by"])
                    }
                elif collectible and collectible["expires_at"] < datetime.now():
                    print(f"⏰ Collectible expired at {collectible['expires_at']}")
                    return {
                        "success": False,
                        "message": "Collectible expired"
                    }
                else:
                    print(f"🚫 Collectible not available (might be inactive)")
                    return {
                        "success": False,
                        "message": "Collectible not available"
                    }

            # SUCCESS! You got it!
            print(f"✅ Claim successful! User {user_id} got {result['name']} ({result['type']})")

            # Add to user's inventory
            inventory_doc = await self.user_collectibles.insert_one({
                "user_id": user_id,
                "collectible_id": coll_oid,  # Store as ObjectId for $lookup to work
                "claimed_at": datetime.now(),
                "claim_order": result["metadata"]["successful_claims"],
                "event_id": result["event_id"]
            })
            print(f"📦 Added to user_collectibles with _id: {inventory_doc.inserted_id}")

            # Update user stats
            await self.db.users.update_one(
                {"_id": ObjectId(user_id)},
                {"$inc": {"stats.collectibles_count": 1}}
            )
            print(f"📊 Updated user stats")

            return {
                "success": True,
                "message": "Collectible claimed successfully!",
                "collectible": result,
                "claim_order": result["metadata"]["successful_claims"]
            }

        except Exception as e:
            print(f"Error claiming collectible: {e}")
            return {
                "success": False,
                "message": f"Error: {str(e)}"
            }

    async def drop_random_collectible(self, event_id: str, location: List[float]):
        """
        Drop a random collectible in an event
        (Called by background task or event trigger)
        """
        # Random rarity based on probability
        rand = random.random()
        if rand < 0.5:
            rarity = "common"  # 50%
        elif rand < 0.8:
            rarity = "rare"  # 30%
        elif rand < 0.95:
            rarity = "epic"  # 15%
        else:
            rarity = "legendary"  # 5%


        collectible = await self.create_collectible(event_id, rarity, location)

        return collectible

    async def expire_old_collectibles(self):
        """
        Background task to mark expired collectibles as inactive
        (Run this every minute via scheduler)
        """
        result = await self.collectibles.update_many(
            {
                "is_active": True,
                "claimed_by": None,
                "expires_at": {"$lt": datetime.now()}
            },
            {"$set": {"is_active": False}}
        )

        return result.modified_count

    async def get_user_inventory(self, user_id: str) -> list:
        """Get all collectibles owned by a user"""
        pipeline = [
            {"$match": {"user_id": user_id}},
            {
                "$lookup": {
                    "from": "collectibles",
                    "localField": "collectible_id",
                    "foreignField": "_id",
                    "as": "collectible"
                }
            },
            {"$unwind": {
                "path": "$collectible",
                "preserveNullAndEmptyArrays": False  # Skip if no match (don't fail)
            }},
            {"$sort": {"claimed_at": -1}}
        ]

        try:
            results = await self.user_collectibles.aggregate(pipeline).to_list(None)
            print(f"📦 Found {len(results)} collectibles for user {user_id}")
            return results
        except Exception as e:
            print(f"❌ Error getting user inventory: {e}")
            return []  # Return empty list on error instead of crashing
