import asyncio
from app.db.session import connect_to_mongo, db_ctx

async def check_db():
    await connect_to_mongo()
    db = db_ctx.db
    
    print("--- Users ---")
    async for user in db.users.find({}):
        print(user.get("username"))
        
    print("\n--- Search History ---")
    async for hist in db.search_history.find({"username": "testuser123"}):
        print(hist)
        
    print("\n--- Chat History ---")
    async for chat in db.chat_history.find({"username": "testuser123"}):
        print(chat)
        
    print("\n--- Gap Reports ---")
    async for report in db.gap_reports.find({"username": "testuser123"}):
        print(f"Report: {report.get('topic')} (ID: {report.get('report_id')})")
        
    db_ctx.client.close()

if __name__ == "__main__":
    asyncio.run(check_db())
