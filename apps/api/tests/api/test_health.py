from fastapi import FastAPI, Response
from httpx import ASGITransport, AsyncClient

from munych_api.shared.http_cache import NoStoreMiddleware


async def test_health(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_unknown_route_returns_problem_json(client: AsyncClient) -> None:
    response = await client.get("/api/v1/no-existe")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["code"] == "NOT_FOUND"
    assert body["status"] == 404
    assert body["detail"] == "Recurso no encontrado"


async def test_responses_are_not_cacheable(client: AsyncClient) -> None:
    ok = await client.get("/api/v1/health")
    assert ok.headers["cache-control"] == "no-store"

    error = await client.get("/api/v1/no-existe")
    assert error.headers["cache-control"] == "no-store"


async def test_explicit_cache_control_is_kept() -> None:
    app = FastAPI()
    app.add_middleware(NoStoreMiddleware)

    @app.get("/cacheable")
    async def cacheable(response: Response) -> dict[str, str]:
        response.headers["Cache-Control"] = "public, max-age=60"
        return {}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get("/cacheable")
    assert response.headers["cache-control"] == "public, max-age=60"


async def test_openapi_uses_function_names_as_operation_ids(client: AsyncClient) -> None:
    response = await client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    assert response.json()["paths"]["/api/v1/health"]["get"]["operationId"] == "health"


async def test_cors_allows_configured_origin_only(client: AsyncClient) -> None:
    allowed = await client.options(
        "/api/v1/health",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"

    denied = await client.options(
        "/api/v1/health",
        headers={"Origin": "https://malicioso.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in denied.headers
