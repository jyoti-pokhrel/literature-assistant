import asyncio
import os
import sys
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

# Add project root to sys.path
sys.path.append(os.getcwd())

async def migrate_search_history():
    load_dotenv()
    mongo_uri = os.environ.get("MONGODB_URL")
    db_name = os.environ.get("DB_NAME", "research_agent")
    
    if not mongo_uri:
        print("Error: MONGODB_URL not found in .env")
        return

    print(f"Connecting to MongoDB...")
    client = AsyncIOMotorClient(mongo_uri)
    db = client[db_name]
    
    print(f"Migrating search_history in database: {db_name}")
    
    # 1. Rename 'query' to 'topic' where 'topic' doesn't exist
    # Note: $rename is a simple way to do this in MongoDB
    result = await db.search_history.update_many(
        {"topic": {"$exists": False}, "query": {"$exists": True}},
        {"$rename": {"query": "topic"}}
    )
    print(f"Renamed 'query' to 'topic' in {result.modified_count} documents.")
    
    # 2. Rename 'result_count' to 'results_count' or vice-versa for consistency
    # I noticed history.py uses 'result_count' while search.py uses 'results_count'
    # Let's standardize on 'results_count' as it's plural and more common in search results
    result_s = await db.search_history.update_many(
        {"results_count": {"$exists": False}, "result_count": {"$exists": True}},
        {"$rename": {"result_count": "results_count"}}
    )
    print(f"Standardized results count field in {result_s.modified_count} documents.")
    
    # 3. Clean up null or empty topics
    result_cleanup = await db.search_history.delete_many(
        {"$or": [
            {"topic": None},
            {"topic": ""},
            {"topic": {"$regex": "^\\s*$"}}
        ]}
    )
    print(f"Cleaned up {result_cleanup.deleted_count} invalid/empty search records.")

    print("\nMigration complete!")

if __name__ == "__main__":
    asyncio.run(migrate_search_history())
