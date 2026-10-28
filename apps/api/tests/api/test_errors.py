from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

from munych_api.config import Settings
from munych_api.main import create_app
from munych_api.shared.kernel import DomainError, ErrorCode


class _Body(BaseModel):
    value: int


async def test_domain_error_and_validation_error_are_problem_json(settings: Settings) -> None:
    app = create_app(settings)

    @app.get("/boom")
    async def boom() -> None:
        raise DomainError(ErrorCode.SESSION_CLOSED, "La sesión 2 está cerrada")

    @app.post("/validate")
    async def validate(body: _Body) -> _Body:
        return body

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        boom_response = await client.get("/boom")
        assert boom_response.status_code == 409
        assert boom_response.headers["content-type"].startswith("application/problem+json")
        assert boom_response.json() == {
            "type": "https://munych.org/problems/session-closed",
            "title": "Conflict",
            "status": 409,
            "code": "SESSION_CLOSED",
            "detail": "La sesión 2 está cerrada",
        }

        invalid = await client.post("/validate", json={"value": "no-es-numero"})
        assert invalid.status_code == 422
        body = invalid.json()
        assert body["code"] == "VALIDATION_ERROR"
        assert body["errors"][0]["loc"] == ["body", "value"]
