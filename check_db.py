import asyncio
import motor.motor_asyncio
import os
from dotenv import load_dotenv

async def main():
    load_dotenv()
    client = motor.motor_asyncio.AsyncIOMotorClient(os.getenv('MONGODB_URL'))
    db = client[os.getenv('DB_NAME', 'research_agent')]
    
    print("--- Search History (last 5) ---")
    cursor = db.search_history.find().sort("created_at", -1).limit(5)
    async for doc in cursor:
        print(doc)
    
    print("\n--- Analytics Aggregate Test ---")
    from datetime import datetime, timedelta, timezone
    pipeline = [
        {
            "$match": {
                "created_at": {"$gte": datetime.now(timezone.utc) - timedelta(days=7)}
            }
        },
        {
            "$group": {
                "_id": {
                    "$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}
                },
                "count": {"$sum": 1}
            }
        },
        {"$sort": {"_id": 1}}
    ]
    results = await db.search_history.aggregate(pipeline).to_list(length=10)
    print(results)
    
    client.close()

if __name__ == "__main__":
    asyncio.run(main())
