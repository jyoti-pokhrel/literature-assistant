import os
from pathlib import Path
import certifi

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient


ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=ENV_PATH)

MONGO_URL = os.getenv("MONGODB_URL") or os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME", "research_agent")

# Use certifi for reliable SSL handshakes on Windows/Atlas
client = AsyncIOMotorClient(MONGO_URL, tlsCAFile=certifi.where()) if MONGO_URL else None
db = client[DB_NAME] if client is not None else None

users_collection = db["users"] if db is not None else None
papers_collection = db["papers"] if db is not None else None
reports_collection = db["reports"] if db is not None else None
gap_reports_collection = db["gap_reports"] if db is not None else None
