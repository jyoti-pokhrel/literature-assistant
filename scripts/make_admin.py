import asyncio
import os
import sys
from pathlib import Path

# Add the project root to sys.path so we can import app
sys.path.append(str(Path(__file__).resolve().parent.parent))


from app.db.session import get_db

async def make_admin(username: str):
    db = get_db()
    if db is None:
        print("Error: Database connection not established. Check your MONGODB_URL in .env.")
        return

    result = await db.users.update_one(
        {"username": username},
        {"$set": {"role": "admin"}}
    )
    
    if result.matched_count == 0:
        print(f"Error: User '{username}' not found in the database.")
    elif result.modified_count > 0:
        print(f"Success: User '{username}' has been promoted to admin!")
    else:
        print(f"User '{username}' is already an admin or no changes were needed.")

if __name__ == "__main__":
    target_user = "Sachu"
    if len(sys.argv) > 1:
        target_user = sys.argv[1]
    
    print(f"Attempting to promote '{target_user}' to admin...")
    asyncio.run(make_admin(target_user))
