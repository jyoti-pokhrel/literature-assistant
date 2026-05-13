from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.security import OAuth2PasswordRequestForm
from app.schemas.user import UserCreate
from app.utils.helpers import hashed_password, verify_password
from app.core.security import create_access_token
from app.db.guards import require_collection
from app.db.session import users_collection

router = APIRouter()

@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def register_user(user: UserCreate):
    collection = require_collection(users_collection, "user signup")
    existing_user = await collection.find_one({"username": user.username})
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already exists")

    hashed_pass = hashed_password(user.password)

    new_user = {
        "username": user.username,
        "email": user.email,
        "hashed_password": hashed_pass,
        "role": user.role
    }

    result = await collection.insert_one(new_user)
    return {
        "id": str(result.inserted_id),
        "username": user.username,
        "email": user.email,
        "role": user.role
    }


@router.post("/login", status_code=status.HTTP_200_OK)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    collection = require_collection(users_collection, "login")
    user = await collection.find_one({"username": form_data.username})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Username"
        )

    if not verify_password(form_data.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Password"
        )

    token_data = {"sub": user["username"], "role": user["role"]}
    token = create_access_token(token_data)
    return {"access_token": token, "token_type": "bearer"}