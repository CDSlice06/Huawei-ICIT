# -*- coding: utf-8 -*-
"""认证与会话测试（tasks.md 3.1/3.2/14.1）：注册校验、默认库预建、防枚举、Cookie/Bearer 双通道。"""
import uuid

REGISTER_EMAIL = "auth-test@test.cn"
VALID_PASSWORD = "Passw0rd123"


async def test_register_success_creates_default_kb(client, session_factory, fake_redis):
    from sqlalchemy import select

    from app.models import KnowledgeBase, User

    resp = await client.post(
        "/api/auth/register", json={"email": REGISTER_EMAIL, "password": VALID_PASSWORD}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["token"]
    assert body["data"]["user"]["email"] == REGISTER_EMAIL

    async with session_factory() as db:
        user = (
            await db.execute(select(User).where(User.email == REGISTER_EMAIL))
        ).scalar_one()
        kbs = (
            await db.execute(
                select(KnowledgeBase).where(KnowledgeBase.user_id == user.id)
            )
        ).scalars().all()
        assert len(kbs) == 1 and kbs[0].name == "默认知识库"


async def test_register_weak_password_422(client):
    for weak in ["short1a", "nodigitpassword", "12345678", "有中文的密码123"]:
        resp = await client.post(
            "/api/auth/register", json={"email": f"{uuid.uuid4().hex[:6]}@t.cn", "password": weak}
        )
        assert resp.status_code == 422, f"{weak} 应被拒绝"
        assert "8~32位" in resp.text


async def test_register_duplicate_email_409(client):
    payload = {"email": "dup@test.cn", "password": VALID_PASSWORD}
    first = await client.post("/api/auth/register", json=payload)
    assert first.status_code == 200
    second = await client.post("/api/auth/register", json=payload)
    assert second.status_code == 409
    assert "已注册" in second.json()["message"]


async def test_login_wrong_credentials_uniform_401(client):
    """防枚举：不存在的邮箱与错误密码返回同一文案（spec §5.1.3异常2）。"""
    for payload in [
        {"email": "ghost@test.cn", "password": "Whatever123"},
        {"email": "dup@test.cn", "password": "WrongPass123"},
    ]:
        resp = await client.post("/api/auth/login", json=payload)
        assert resp.status_code == 401
        assert resp.json()["message"] == "邮箱或密码错误"


async def test_login_success_sets_httponly_cookie(client, fake_redis):
    await client.post(
        "/api/auth/register", json={"email": "cookie@test.cn", "password": VALID_PASSWORD}
    )
    resp = await client.post(
        "/api/auth/login", json={"email": "cookie@test.cn", "password": VALID_PASSWORD}
    )
    assert resp.status_code == 200
    set_cookie = resp.headers["set-cookie"]
    assert "mw_token=" in set_cookie and "HttpOnly" in set_cookie

    # Cookie 双通道：me 接口可解析
    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["data"]["email"] == "cookie@test.cn"


async def test_me_and_logout_flow(client, fake_redis):
    reg = await client.post(
        "/api/auth/register", json={"email": "logout@test.cn", "password": VALID_PASSWORD}
    )
    token = reg.json()["data"]["token"]

    # Bearer 双通道
    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200

    # logout 后会话删除，me 返回 401
    out = await client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert out.status_code == 200
    me2 = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me2.status_code == 401


async def test_session_ttl_at_least_24h(client, fake_redis):
    await client.post(
        "/api/auth/register", json={"email": "ttl@test.cn", "password": VALID_PASSWORD}
    )
    keys = [k for k in fake_redis._store if k.startswith("session:")]
    assert keys
    # FakeRedis 未启用 ex 时不存过期；直接校验 config 约束
    from app.config import settings

    assert settings.session_ttl_seconds >= 86400


async def test_unauthenticated_protected_route_401(client):
    resp = await client.get("/api/cards")
    assert resp.status_code == 401
    resp2 = await client.get(
        "/api/cards", headers={"Authorization": "Bearer forged-token"}
    )
    assert resp2.status_code == 401
