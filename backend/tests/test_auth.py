"""Sign-up, login, logout, sessions and password storage."""
import datetime

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token
from app.models.models import RevokedToken, User
from tests.helpers import AAYUSH, client, login


async def test_passwords_are_stored_as_bcrypt_hashes_never_plaintext():
    async with AsyncSessionLocal() as s:
        users = (await s.execute(select(User))).scalars().all()
    assert len(users) >= 8
    for user in users:
        assert user.hashed_password.startswith("$2") and "Password123!" not in user.hashed_password
        assert len(user.hashed_password) == 60
    assert len({u.hashed_password for u in users}) == len(users)  # salted: same password, different hashes


async def test_sign_up_validates_input_and_rejects_duplicates():
    async with client() as c:
        base = {"email": "valid.person@example.com", "password": "Password123!", "name": "Valid Person", "org_id": "himali-tea"}
        assert (await c.post("/api/auth/register", json={**base, "password": "short"})).status_code == 422
        assert (await c.post("/api/auth/register", json={**base, "name": "   "})).status_code == 422
        assert (await c.post("/api/auth/register", json={**base, "email": "not-an-email"})).status_code == 422
        assert (await c.post("/api/auth/register", json={**base, "org_id": "no-such-org"})).status_code == 404
        assert (await c.post("/api/auth/register", json=base)).status_code == 200
        again = await c.post("/api/auth/register", json=base)
        assert again.status_code == 400 and "already exists" in again.json()["detail"]
        # The same email is a different person in a different organisation.
        other_org = await c.post("/api/auth/register", json={**base, "org_id": "lotus-wellness"})
        assert other_org.status_code == 200 and other_org.json()["user"]["org_id"] == "org_b"


async def test_login_returns_the_user_and_a_working_session():
    async with client() as c:
        res = await c.post("/api/auth/login", json={"email": "AAYUSH@himali.test", "password": "Password123!", "org_id": "himali-tea"})
        assert res.status_code == 200  # the entry point can be given as the slug, and email case does not matter
        body = res.json()
        assert body["token_type"] == "bearer" and body["user"]["email"] == "aayush@himali.test"
        me = await c.get("/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
        assert me.status_code == 200 and me.json()["id"] == "user_a1"
        assert "hashed_password" not in me.text and "hashed_password" not in res.text


async def test_logout_revokes_that_token_only():
    async with client() as c:
        first, second = await login(c, AAYUSH), await login(c, AAYUSH)  # two sessions of one user
        assert (await c.get("/api/auth/me", headers=first)).status_code == 200
        out = await c.post("/api/auth/logout", headers=first)
        assert out.status_code == 200
        assert (await c.get("/api/auth/me", headers=first)).status_code == 401  # the signed-out token is dead
        assert (await c.get("/api/orders", headers=first)).status_code == 401
        assert (await c.get("/api/auth/me", headers=second)).status_code == 200  # the other session is untouched
        assert (await c.post("/api/auth/logout", headers=first)).status_code == 401  # and cannot be revoked twice
    async with AsyncSessionLocal() as s:
        assert (await s.execute(select(RevokedToken).where(RevokedToken.user_id == "user_a1"))).scalars().first()


async def test_expired_tokens_are_refused():
    token = create_access_token({"sub": "user_a1", "org_id": "org_a"}, expires_delta=datetime.timedelta(seconds=-1))
    async with client() as c:
        assert (await c.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})).status_code == 401


async def test_repeated_login_attempts_are_throttled_per_client_and_email():
    async with client() as c:
        attempt = {"email": "aayush@himali.test", "password": "wrong-password-1", "org_id": "org_a"}
        codes = [(await c.post("/api/auth/login", json=attempt)).status_code for _ in range(12)]
        assert codes[:10] == [401] * 10 and codes[10:] == [429, 429]
        # Someone else's account, from the same client, is not locked out by this.
        fine = await c.post("/api/auth/login", json={"email": "priya@himali.test", "password": "Password123!", "org_id": "org_a"})
        assert fine.status_code == 200


async def test_cors_only_allows_the_configured_front_end_origins():
    async with client() as c:
        ok = await c.options("/api/orders", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"})
        bad = await c.options("/api/orders", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert "access-control-allow-origin" not in bad.headers
    assert "access-control-allow-credentials" not in ok.headers  # no cookies are used, so none are allowed


async def test_health_endpoint_needs_no_login_and_reports_the_provider():
    async with client() as c:
        res = await c.get("/api/health")
    assert res.status_code == 200 and res.json()["status"] == "healthy" and res.json()["llm_provider"] == "mock"


async def test_owner_can_create_rename_and_delete_conversations_and_deleting_removes_the_messages():
    from app.models.models import Message
    from tests.helpers import chat, new_conversation

    async with client() as c:
        headers = await login(c, AAYUSH)
        conv = await new_conversation(c, headers)
        await chat(c, headers, conv, "What teas do you have?")
        renamed = await c.patch(f"/api/chat/conversations/{conv}", headers=headers, json={"title": "My tea questions"})
        assert renamed.status_code == 200 and renamed.json()["title"] == "My tea questions"
        listed = (await c.get("/api/chat/conversations", headers=headers)).json()
        assert next(x for x in listed if x["id"] == conv)["title"] == "My tea questions"
        assert (await c.delete(f"/api/chat/conversations/{conv}", headers=headers)).status_code == 200
        assert (await c.get(f"/api/chat/conversations/{conv}/messages", headers=headers)).status_code == 404
        assert conv not in {x["id"] for x in (await c.get("/api/chat/conversations", headers=headers)).json()}
    async with AsyncSessionLocal() as s:
        assert (await s.execute(select(Message).where(Message.conversation_id == conv))).scalars().all() == []


async def test_a_new_chat_is_titled_from_its_first_message():
    from tests.helpers import chat, new_conversation

    async with client() as c:
        headers = await login(c, AAYUSH)
        conv = await new_conversation(c, headers)
        await chat(c, headers, conv, "Do you have any good oolong teas under 2000 rupees please?")
        title = next(x for x in (await c.get("/api/chat/conversations", headers=headers)).json() if x["id"] == conv)["title"]
    assert title.startswith("Do you have any good oolong") and title != "New Chat"
