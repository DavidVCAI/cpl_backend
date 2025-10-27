"""
Cleanup script to remove duplicate participants from events
Run this once to fix existing database issues
"""
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

MONGODB_URL = os.getenv("MONGODB_URL")

async def cleanup_duplicate_participants():
    """Remove duplicate participants from all events"""
    client = AsyncIOMotorClient(MONGODB_URL)
    db = client.citypulse_live

    print("Finding events with duplicate participants...")

    # Get all events
    events = await db.events.find({}).to_list(1000)

    fixed_count = 0

    for event in events:
        event_id = event["_id"]
        participants = event.get("participants", [])

        if not participants:
            continue

        # Find unique participants by user_id (keep first occurrence)
        seen_user_ids = set()
        unique_participants = []
        duplicates_removed = 0

        for participant in participants:
            user_id = participant.get("user_id")
            if user_id and user_id not in seen_user_ids:
                seen_user_ids.add(user_id)
                unique_participants.append(participant)
            else:
                duplicates_removed += 1

        # Update event if duplicates were found
        if duplicates_removed > 0:
            print(f"\nEvent {event_id}:")
            print(f"   - Original participants: {len(participants)}")
            print(f"   - Unique participants: {len(unique_participants)}")
            print(f"   - Duplicates removed: {duplicates_removed}")

            # Update the event
            await db.events.update_one(
                {"_id": event_id},
                {
                    "$set": {
                        "participants": unique_participants,
                        "room.current_participants": len(unique_participants),
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            fixed_count += 1

    print(f"\nCleanup complete! Fixed {fixed_count} events")

    client.close()

if __name__ == "__main__":
    asyncio.run(cleanup_duplicate_participants())
