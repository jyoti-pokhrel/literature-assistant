import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import motor.motor_asyncio

# Add the project root to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))

async def make_system_user(username: str):
    env_path = Path(__file__).resolve().parent.parent / '.env'
    load_dotenv(dotenv_path=env_path)
    
    mongo_url = os.getenv('MONGODB_URL')
    if not mongo_url:
        print("Error: MONGODB_URL is not set in .env")
        return

    client = motor.motor_asyncio.AsyncIOMotorClient(mongo_url)
    db = client[os.getenv('DB_NAME', 'research_agent')]
    
    result = await db.users.update_one(
        {"username": username},
        {"$set": {"role": "system_user", "is_verified": True}}
    )
    
    if result.matched_count == 0:
        print(f"Error: User '{username}' not found in the database.")
    elif result.modified_count > 0:
        print(f"Success: User '{username}' has been promoted to system_user!")
    else:
        print(f"User '{username}' is already a system_user or no changes were needed.")
        
    client.close()

if __name__ == "__main__":
    target_user = "Sachu"
    if len(sys.argv) > 1:
        target_user = sys.argv[1]
    
    print(f"Attempting to promote '{target_user}' to system_user...")
    asyncio.run(make_system_user(target_user))
