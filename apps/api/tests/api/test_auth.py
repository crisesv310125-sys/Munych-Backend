"""Autenticación y roles (sin base de datos)."""

import uuid

from httpx import AsyncClient

from tests.support.auth import bearer, make_token


async def test_missing_token_returns_401(client: AsyncClient) -> None:
    response = await client.get("/api/v1/me")
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"
    assert response.headers["www-authenticate"] == "Bearer"


async def test_invalid_token_returns_401(client: AsyncClient) -> None:
    response = await client.get("/api/v1/me", headers=bearer("x.y.z"))
    assert response.status_code == 401
    assert response.json()["detail"] == "Token inválido o expirado"


async def test_expired_token_returns_401(client: AsyncClient) -> None:
    token = make_token(uuid.uuid4(), expires_in=-300)  # fuera de la tolerancia de reloj
    response = await client.get("/api/v1/me", headers=bearer(token))
    assert response.status_code == 401


async def test_judge_cannot_use_admin_endpoints(client: AsyncClient) -> None:
    token = make_token(uuid.uuid4(), role="judge")
    response = await client.get("/api/v1/judges", headers=bearer(token))
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


async def test_user_without_role_cannot_use_admin_endpoints(client: AsyncClient) -> None:
    token = make_token(uuid.uuid4(), role=None)
    response = await client.post(
        "/api/v1/judges", headers=bearer(token), json={"email": "a@b.org", "full_name": "A"}
    )
    assert response.status_code == 403
