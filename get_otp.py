import asyncio
from app.db.session import connect_to_mongo, db_ctx

async def get_otp():
    await connect_to_mongo()
    db = db_ctx.db
    otp_doc = await db.otps.find_one({"email": "testuser123@example.com"})
    if otp_doc:
        print(f"OTP: {otp_doc['otp']}")
    else:
        print("OTP not found")
    db_ctx.client.close()

if __name__ == "__main__":
    asyncio.run(get_otp())
