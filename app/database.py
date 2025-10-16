from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING, DESCENDING
from app.config import settings
import logging

logger = logging.getLogger(__name__)

# Global database client
client: AsyncIOMotorClient = None
database = None


async def get_database():
    """Get database instance"""
    global database
    if database is None:
        global client
        client = AsyncIOMotorClient(settings.MONGODB_URL)
        database = client[settings.DATABASE_NAME]
        logger.info(f"✅ Connected to MongoDB database: {settings.DATABASE_NAME}")
    return database


async def close_database():
    """Close database connection"""
    global client
    if client:
        client.close()
        logger.info("✅ MongoDB connection closed")


async def init_database():
    """Initialize database with collections and indexes"""
    db = await get_database()

    logger.info("🔧 Initializing database indexes...")

    # USERS Collection Indexes
    await db.users.create_index("phone", unique=True)
    await db.users.create_index([("current_location", "2dsphere")])
    logger.info("✅ Users indexes created")

    # EVENTS Collection Indexes
    await db.events.create_index([("location", "2dsphere")])
    await db.events.create_index([("status", ASCENDING), ("created_at", DESCENDING)])
    await db.events.create_index("creator_id")
    logger.info("✅ Events indexes created")

    # COLLECTIBLES Collection Indexes
    await db.collectibles.create_index("event_id")
    await db.collectibles.create_index("claimed_by")
    await db.collectibles.create_index([("is_active", ASCENDING), ("expires_at", ASCENDING)])
    logger.info("✅ Collectibles indexes created")

    # USER_COLLECTIBLES Collection Indexes
    await db.user_collectibles.create_index("user_id")
    await db.user_collectibles.create_index("collectible_id")
    await db.user_collectibles.create_index([("user_id", ASCENDING), ("claimed_at", DESCENDING)])
    logger.info("✅ User collectibles indexes created")

    # TRANSCRIPTIONS Collection Indexes
    await db.transcriptions.create_index("event_id")
    await db.transcriptions.create_index("created_at")
    logger.info("✅ Transcriptions indexes created")

    logger.info("🎉 Database initialization complete!")
