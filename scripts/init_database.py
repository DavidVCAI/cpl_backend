"""
MongoDB Database Initialization Script

This script creates the database, collections, and indexes for CityPulse Live.
Run this once after setting up your MongoDB connection.

Usage:
    python scripts/init_database.py
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import init_database, get_database, close_database
from app.config import settings
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    """Initialize database with collections and indexes"""
    try:
        logger.info(f"🔧 Connecting to MongoDB: {settings.DATABASE_NAME}")

        # Initialize database and create indexes
        await init_database()

        db = await get_database()

        # List all collections
        collections = await db.list_collection_names()
        logger.info(f"📦 Available collections: {collections}")

        # Show indexes for each collection
        for collection_name in ["users", "events", "collectibles", "user_collectibles", "transcriptions"]:
            if collection_name in collections:
                indexes = await db[collection_name].list_indexes().to_list(None)
                logger.info(f"\n📋 Indexes for {collection_name}:")
                for idx in indexes:
                    logger.info(f"  - {idx['name']}: {idx.get('key', {})}")

        logger.info("\n✅ Database initialization complete!")
        logger.info(f"✅ Database: {settings.DATABASE_NAME}")
        logger.info(f"✅ Connection: {settings.MONGODB_URL[:50]}...")

    except Exception as e:
        logger.error(f"❌ Error initializing database: {e}")
        raise

    finally:
        await close_database()


if __name__ == "__main__":
    asyncio.run(main())
