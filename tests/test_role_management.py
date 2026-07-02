import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.api.dependencies import get_current_admin
from app.db.session import get_db

# Mock database dependency for tests
class MockDB:
    def __init__(self):
        self.users = self.MockCollection()

    class MockCollection:
        def __init__(self):
            self.data = [
                {"_id": "sys_1", "username": "Sachu", "email": "sachu@agent.ai", "role": "system_user", "is_active": True},
                {"_id": "adm_1", "username": "admin1", "email": "admin1@agent.ai", "role": "admin", "is_active": True},
                {"_id": "adm_2", "username": "admin2", "email": "admin2@agent.ai", "role": "admin", "is_active": True},
                {"_id": "res_1", "username": "res1", "email": "res1@agent.ai", "role": "researcher", "is_active": True},
            ]

        async def find_one(self, query):
            for item in self.data:
                if "username" in query and item["username"] == query["username"]:
                    return item
                if "email" in query and item["email"] == query["email"]:
                    return item
                if "role" in query and item["role"] == query["role"]:
                    return item
            return None

        async def update_one(self, query, update):
            user = await self.find_one(query)
            if user:
                set_data = update.get("$set", {})
                for k, v in set_data.items():
                    user[k] = v
                return type('obj', (object,), {'matched_count': 1, 'modified_count': 1})
            return type('obj', (object,), {'matched_count': 0, 'modified_count': 0})

        async def delete_one(self, query):
            user = await self.find_one(query)
            if user:
                self.data.remove(user)
                return type('obj', (object,), {'deleted_count': 1})
            return type('obj', (object,), {'deleted_count': 0})

        def find(self, query=None, projection=None):
            class MockCursor:
                def __init__(self, data):
                    self.data = data
                def __aiter__(self):
                    return self
                async def __anext__(self):
                    if not self.data:
                        raise StopAsyncIteration
                    return self.data.pop(0)
            
            res_data = [item.copy() for item in self.data if not query or query.get("role") == item["role"]]
            return MockCursor(res_data)

mock_db = MockDB()

INITIAL_DATA = [
    {"_id": "sys_1", "username": "Sachu", "email": "sachu@agent.ai", "role": "system_user", "is_active": True},
    {"_id": "adm_1", "username": "admin1", "email": "admin1@agent.ai", "role": "admin", "is_active": True},
    {"_id": "adm_2", "username": "admin2", "email": "admin2@agent.ai", "role": "admin", "is_active": True},
    {"_id": "res_1", "username": "res1", "email": "res1@agent.ai", "role": "researcher", "is_active": True},
]

@pytest.fixture(autouse=True)
def mock_mongo_collections(monkeypatch):
    import app.api.routes.admin as admin_routes
    import app.api.dependencies as deps
    import app.db.session as session
    import copy

    # Reset mock data before each test
    mock_db.users.data = copy.deepcopy(INITIAL_DATA)

    monkeypatch.setattr(admin_routes, "get_db", lambda: mock_db)
    monkeypatch.setattr(deps, "users_collection", mock_db.users)
    monkeypatch.setattr(session, "users_collection", mock_db.users)

@pytest.mark.anyio
async def test_system_user_dashboard_access_by_admin():
    # Admin attempts to access System Dashboard stats
    async def mock_admin_user():
        return {"_id": "adm_1", "username": "admin1", "role": "admin"}

    app.dependency_overrides[get_current_admin] = mock_admin_user
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/admin/system-dashboard-stats")
    
    assert response.status_code == 403
    assert "Permission Denied" in response.json()["detail"]

@pytest.mark.anyio
async def test_system_user_dashboard_access_by_system_user():
    # System User accesses System Dashboard stats
    async def mock_system_user():
        return {"_id": "sys_1", "username": "Sachu", "role": "system_user"}

    app.dependency_overrides[get_current_admin] = mock_system_user
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/admin/system-dashboard-stats")
        
    assert response.status_code == 200
    data = response.json()
    assert "admins" in data
    assert len(data["admins"]) > 0

@pytest.mark.anyio
async def test_admin_cannot_delete_other_admin():
    # Admin attempts to delete another Admin
    async def mock_admin_user():
        return {"_id": "adm_1", "username": "admin1", "role": "admin"}

    app.dependency_overrides[get_current_admin] = mock_admin_user
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.delete("/admin/users/admin2")
        
    assert response.status_code == 403
    assert "Admins cannot delete other Admin accounts" in response.json()["detail"]

@pytest.mark.anyio
async def test_system_user_can_delete_admin():
    # System User deletes an Admin
    async def mock_system_user():
        return {"_id": "sys_1", "username": "Sachu", "role": "system_user"}

    app.dependency_overrides[get_current_admin] = mock_system_user
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.delete("/admin/users/admin2")
        
    assert response.status_code == 200
    assert response.json()["message"] == "User deleted successfully"

@pytest.mark.anyio
async def test_system_user_cannot_be_deleted():
    # System User tries to delete Sachu
    async def mock_system_user():
        return {"_id": "sys_1", "username": "Sachu", "role": "system_user"}

    app.dependency_overrides[get_current_admin] = mock_system_user
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.delete("/admin/users/Sachu")
        
    assert response.status_code == 403
    assert "The System User account cannot be deleted" in response.json()["detail"]

@pytest.mark.anyio
async def test_admin_cannot_edit_admin():
    # Admin attempts to edit another Admin's quota
    async def mock_admin_user():
        return {"_id": "adm_1", "username": "admin1", "role": "admin"}

    app.dependency_overrides[get_current_admin] = mock_admin_user
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.patch("/admin/users/admin2", json={"quota_limit": 500})
        
    assert response.status_code == 403
    assert "Admins cannot edit other Admin accounts" in response.json()["detail"]

@pytest.mark.anyio
async def test_system_user_can_edit_admin():
    # System User demotes an Admin
    async def mock_system_user():
        return {"_id": "sys_1", "username": "Sachu", "role": "system_user"}

    app.dependency_overrides[get_current_admin] = mock_system_user
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.patch("/admin/users/admin2", json={"role": "researcher"})
        
    assert response.status_code == 200
    assert response.json()["updated"]["role"] == "researcher"
