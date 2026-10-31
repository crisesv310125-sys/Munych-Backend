"""/me y gestión de jueces contra la BD de integración."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.support.auth import bearer, make_token
from tests.support.seed import ADMIN_ID, EVENT_ID, JUDGE_1_ID
from tests.support.supabase import FakeSupabase

pytestmark = pytest.mark.integration

ADMIN = bearer(make_token(ADMIN_ID, role="admin", email="admin@munych.dev"))


async def test_me_for_admin_and_judge(client: AsyncClient) -> None:
    admin = await client.get("/api/v1/me", headers=ADMIN)
    assert admin.status_code == 200
    assert admin.json() == {
        "user_id": ADMIN_ID,
        "email": "admin@munych.dev",
        "role": "admin",
        "full_name": None,
    }

    judge_token = make_token(JUDGE_1_ID, role="judge", email="juez1@munych.dev")
    judge = await client.get("/api/v1/me", headers=bearer(judge_token))
    assert judge.json()["full_name"] == "Laura Méndez"
    assert judge.json()["role"] == "judge"


async def test_list_judges_is_paginated(client: AsyncClient) -> None:
    response = await client.get("/api/v1/judges?limit=1&offset=0", headers=ADMIN)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 2
    assert len(body["items"]) == 1
    assert set(body["items"][0]) == {"judge_id", "email", "full_name", "active"}


async def test_invite_new_judge_creates_judge_and_role(
    client: AsyncClient, fake_supabase: FakeSupabase
) -> None:
    email = f"nuevo-{uuid.uuid4().hex[:8]}@munych.dev"
    response = await client.post(
        "/api/v1/judges", headers=ADMIN, json={"email": email, "full_name": " Nueva Jueza "}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email"] == email
    assert body["full_name"] == "Nueva Jueza"
    assert body["active"] is True
    assert fake_supabase.invited == [email]
    assert fake_supabase.invite_redirects == ["http://localhost:5173"]
    assert fake_supabase.invite_data == [{"full_name": "Nueva Jueza"}]


async def test_invite_sends_event_data_for_email_template(
    client: AsyncClient, fake_supabase: FakeSupabase
) -> None:
    email = f"evento-{uuid.uuid4().hex[:8]}@munych.dev"
    body = {"email": email, "full_name": "Ana Pérez", "event_id": EVENT_ID}
    response = await client.post("/api/v1/judges", headers=ADMIN, json=body)
    assert response.status_code == 201, response.text
    expected = {
        "full_name": "Ana Pérez",
        "event_name": "SD-MUN 2026",
        "event_dates": "9–11 de octubre de 2026",
        "event_host": "Santo Domingo",
    }
    assert fake_supabase.invite_data == [expected]

    # Reinvitar a un usuario sin confirmar: GoTrue no toca su metadata, así que se actualiza aparte.
    again = await client.post("/api/v1/judges", headers=ADMIN, json=body)
    assert fake_supabase.metadata_updates == [(uuid.UUID(again.json()["judge_id"]), expected)]
    assert fake_supabase.invited == [email, email]

    unknown = await client.post(
        "/api/v1/judges", headers=ADMIN, json={**body, "event_id": str(uuid.uuid4())}
    )
    assert unknown.status_code == 404


async def test_invited_judge_is_listed_only_after_accepting(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    async def listed_ids() -> set[str]:
        response = await client.get("/api/v1/judges?limit=200", headers=ADMIN)
        return {item["judge_id"] for item in response.json()["items"]}

    email = f"pendiente-{uuid.uuid4().hex[:8]}@munych.dev"
    created = await client.post(
        "/api/v1/judges", headers=ADMIN, json={"email": email, "full_name": "Pendiente"}
    )
    judge_id = created.json()["judge_id"]
    assert judge_id not in await listed_ids()

    # Aceptar la invitación = Supabase llena `email_confirmed_at` al abrir el enlace.
    async with engine.begin() as conn:
        await conn.execute(
            text("update auth.users set email_confirmed_at = now() where id = :id"),
            {"id": judge_id},
        )
    assert judge_id in await listed_ids()


async def test_pending_invitations_can_be_listed_and_resent(
    client: AsyncClient, fake_supabase: FakeSupabase, engine: AsyncEngine
) -> None:
    email = f"reenviar-{uuid.uuid4().hex[:8]}@munych.dev"
    created = await client.post(
        "/api/v1/judges", headers=ADMIN, json={"email": email, "full_name": "Por Aceptar"}
    )
    judge_id = created.json()["judge_id"]

    pending = await client.get("/api/v1/judges/invitations?limit=200", headers=ADMIN)
    assert pending.status_code == 200
    item = next(i for i in pending.json()["items"] if i["judge_id"] == judge_id)
    assert item["email"] == email
    assert item["full_name"] == "Por Aceptar"
    assert item["invited_at"] is not None

    resent = await client.post(f"/api/v1/judges/{judge_id}/invitation", headers=ADMIN)
    assert resent.status_code == 200, resent.text
    assert fake_supabase.invited == [email, email]

    # Volver a invitar el mismo correo también reenvía y no duplica al juez.
    again = await client.post(
        "/api/v1/judges", headers=ADMIN, json={"email": email, "full_name": "Por Aceptar"}
    )
    assert again.json()["judge_id"] == judge_id
    assert fake_supabase.invited == [email, email, email]

    async with engine.begin() as conn:
        await conn.execute(
            text("update auth.users set email_confirmed_at = now() where id = :id"),
            {"id": judge_id},
        )
    accepted = await client.post(f"/api/v1/judges/{judge_id}/invitation", headers=ADMIN)
    assert accepted.status_code == 409
    assert accepted.json()["code"] == "CONFLICT"
    pending = await client.get("/api/v1/judges/invitations?limit=200", headers=ADMIN)
    assert judge_id not in {i["judge_id"] for i in pending.json()["items"]}

    missing = await client.post(f"/api/v1/judges/{uuid.uuid4()}/invitation", headers=ADMIN)
    assert missing.status_code == 404


async def test_invite_existing_user_reuses_it(
    client: AsyncClient, fake_supabase: FakeSupabase
) -> None:
    response = await client.post(
        "/api/v1/judges",
        headers=ADMIN,
        json={"email": "JUEZ1@munych.dev", "full_name": "Laura Méndez"},
    )
    assert response.status_code == 201
    assert response.json()["judge_id"] == JUDGE_1_ID
    assert fake_supabase.invited == []


async def test_invite_admin_email_is_conflict(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/judges", headers=ADMIN, json={"email": "admin@munych.dev", "full_name": "X"}
    )
    assert response.status_code == 409
    assert response.json()["code"] == "CONFLICT"


async def test_update_judge(client: AsyncClient) -> None:
    email = f"editar-{uuid.uuid4().hex[:8]}@munych.dev"
    created = await client.post(
        "/api/v1/judges", headers=ADMIN, json={"email": email, "full_name": "Temporal"}
    )
    judge_id = created.json()["judge_id"]

    response = await client.patch(
        f"/api/v1/judges/{judge_id}", headers=ADMIN, json={"full_name": "Editada", "active": False}
    )
    assert response.status_code == 200
    assert response.json()["full_name"] == "Editada"
    assert response.json()["active"] is False

    missing = await client.patch(f"/api/v1/judges/{uuid.uuid4()}", headers=ADMIN, json={})
    assert missing.status_code == 404
    assert missing.json()["code"] == "NOT_FOUND"


async def test_invalid_email_is_validation_error(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/judges", headers=ADMIN, json={"email": "no-es-correo", "full_name": "X"}
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
