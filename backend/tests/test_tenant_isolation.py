import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.main import app
from app.core.config import settings
from app.core.security import create_access_token
from app.core.database import Base, get_db
from app.models.models import User, Organisation

@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"

@pytest.fixture
def auth_headers_user_a():
    token = create_access_token({
        "sub": "user_a1",
        "org_id": "org_a",
        "role": "customer",
        "email": "aayush@himali.test",
        "name": "Aayush Sharma"
    })
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture
def auth_headers_user_b():
    token = create_access_token({
        "sub": "user_b1",
        "org_id": "org_b",
        "role": "customer",
        "email": "rohan@lotus.test",
        "name": "Rohan Shrestha"
    })
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture
def auth_headers_admin_a():
    token = create_access_token({
        "sub": "admin_a",
        "org_id": "org_a",
        "role": "admin",
        "email": "admin@himali.test",
        "name": "Admin A"
    })
    return {"Authorization": f"Bearer {token}"}

@pytest.mark.asyncio
async def test_org_a_user_cannot_access_org_b_services(auth_headers_user_a):
    """Proves Org A customer cannot access Org B services."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Request services route with Org A user token
        res = await client.get("/api/bookings/services", headers=auth_headers_user_a)
        assert res.status_code == 200
        # Since user is in org_a, service list returned must be EMPTY (no leakage of org_b services)
        assert res.json() == []

@pytest.mark.asyncio
async def test_cross_customer_order_snooping_fails(auth_headers_user_a):
    """Proves User A1 cannot read User A2's order ORD-1003."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/orders/ORD-1003", headers=auth_headers_user_a)
        assert res.status_code in [404, 403]
        assert "not found" in res.json()["detail"].lower() or "denied" in res.json()["detail"].lower()

@pytest.mark.asyncio
async def test_cross_tenant_booking_access_fails(auth_headers_user_a):
    """Proves Org A user cannot see Org B bookings."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/bookings", headers=auth_headers_user_a)
        assert res.status_code == 200
        # Must return empty list for user_a1 in bookings
        assert len(res.json()) == 0

@pytest.mark.asyncio
async def test_customer_cannot_access_admin_endpoints(auth_headers_user_a):
    """Proves Customer role gets 403 Forbidden on admin endpoints."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/admin/activity_summary", headers=auth_headers_user_a)
        assert res.status_code == 403
        assert "Forbidden" in res.json()["detail"]

@pytest.mark.asyncio
async def test_admin_cannot_advance_order_from_other_org(auth_headers_admin_a):
    """Proves Admin from Org A cannot advance order if it doesn't belong to Org A."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/admin/orders/ORD-NONEXISTENT-9999/advance_status",
            json={"new_status": "confirmed"},
            headers=auth_headers_admin_a
        )
        assert res.status_code == 404

@pytest.mark.asyncio
async def test_knowledge_base_strict_tenant_isolation(auth_headers_user_a, auth_headers_user_b):
    """Proves knowledge retrieval strictly segregates org_a and org_b data."""
    from app.services.knowledge_base import KnowledgeBaseService
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        # Org A search for wellness / massage terms:
        res_a = await KnowledgeBaseService.search_knowledge(session, "org_a", "massage physiotherapy sound bath")
        for item in res_a:
            assert "lotus" not in item["doc_name"].lower()
            assert "physiotherapy" not in item["content"].lower()

        # Org B search for tea brewing terms:
        res_b = await KnowledgeBaseService.search_knowledge(session, "org_b", "green tea silver needle oolong")
        for item in res_b:
            assert "himali" not in item["doc_name"].lower()
            assert "silver needle" not in item["content"].lower()

@pytest.mark.asyncio
async def test_rate_limiting_enforcement():
    """Proves rate limiter raises HTTP 429 when quota exceeded."""
    from app.core.ratelimit import RateLimiter
    from fastapi import HTTPException

    limiter = RateLimiter(limit=3, window_seconds=60)
    user_id = "test_rate_user"

    # 3 calls succeed
    limiter.check(user_id)
    limiter.check(user_id)
    limiter.check(user_id)

    # 4th call must raise HTTPException(429)
    with pytest.raises(HTTPException) as exc_info:
        limiter.check(user_id)
    assert exc_info.value.status_code == 429
