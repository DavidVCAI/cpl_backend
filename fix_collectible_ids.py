"""
Script to fix collectible_id in user_collectibles collection
Converts string collectible_id to ObjectId so $lookup works properly
"""
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
import os
from dotenv import load_dotenv

load_dotenv()
MONGODB_URL = os.getenv("MONGODB_URL")

async def fix_collectible_ids():
    """Convert string collectible_id to ObjectId in user_collectibles"""
    client = AsyncIOMotorClient(MONGODB_URL)
    db = client.citypulse_live

    print("Finding user_collectibles with string collectible_id...")

    # Find all user_collectibles
    items = await db.user_collectibles.find({}).to_list(1000)
    fixed_count = 0

    for item in items:
        collectible_id = item.get("collectible_id")

        # Check if it's a string (need to convert to ObjectId)
        if isinstance(collectible_id, str):
            try:
                # Convert to ObjectId
                oid = ObjectId(collectible_id)

                # Update the document
                result = await db.user_collectibles.update_one(
                    {"_id": item["_id"]},
                    {"$set": {"collectible_id": oid}}
                )

                if result.modified_count > 0:
                    print(f"[OK] Fixed: {item['_id']} - converted '{collectible_id}' to ObjectId")
                    fixed_count += 1
            except Exception as e:
                print(f"[ERROR] Error fixing {item['_id']}: {e}")
        elif isinstance(collectible_id, ObjectId):
            print(f"[SKIP] Already ObjectId: {item['_id']}")
        else:
            print(f"[WARN] Unknown type for {item['_id']}: {type(collectible_id)}")

    print(f"\n[DONE] Fixed {fixed_count} documents")

    # Now test the lookup query
    print("\n[TEST] Testing $lookup query...")
    pipeline = [
        {"$match": {}},
        {
            "$lookup": {
                "from": "collectibles",
                "localField": "collectible_id",
                "foreignField": "_id",
                "as": "collectible"
            }
        },
        {"$unwind": "$collectible"}
    ]

    results = await db.user_collectibles.aggregate(pipeline).to_list(None)
    print(f"[RESULT] Found {len(results)} collectibles in inventory with successful $lookup")

    for result in results:
        print(f"  - User: {result['user_id']}, Collectible: {result['collectible']['name']} ({result['collectible']['type']})")

    client.close()

if __name__ == "__main__":
    asyncio.run(fix_collectible_ids())
