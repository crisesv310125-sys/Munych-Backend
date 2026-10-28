"""Seguridad del esquema: RLS, privilegios, inmutabilidad y auth hook (sección 9)."""

import json
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.conftest import ADMIN_ID, EVENT_ID, JUDGE_1_ID, ORG_ID

pytestmark = pytest.mark.integration

APP_TABLES = [
    "organizations",
    "user_roles",
    "judges",
    "events",
    "committees",
    "delegations",
    "delegates",
    "committee_judges",
    "event_judges",
    "rubrics",
    "criteria",
    "scoring_sessions",
    "scores",
    "awards",
    "result_snapshots",
    "audit_log",
]


async def _fails(conn: AsyncConnection, sql: str, params: dict[str, Any] | None = None) -> str:
    """Ejecuta `sql` en un savepoint y devuelve el mensaje de error (falla si no hay error)."""
    savepoint = await conn.begin_nested()
    try:
        await conn.execute(text(sql), params or {})
    except DBAPIError as exc:
        await savepoint.rollback()
        return str(exc.orig)
    await savepoint.rollback()
    pytest.fail(f"Se esperaba un error al ejecutar: {sql}")


async def _as_role(conn: AsyncConnection, role: str) -> None:
    await conn.execute(text(f"set local role {role}"))


async def test_rls_enabled_on_every_app_table(conn: AsyncConnection) -> None:
    rows = await conn.execute(
        text(
            "select c.relname, c.relrowsecurity from pg_class c "
            "join pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname = 'app' and c.relkind = 'r'"
        )
    )
    flags = dict(rows.all())
    assert set(APP_TABLES) <= set(flags)
    assert all(flags.values()), flags


@pytest.mark.parametrize("role", ["anon", "authenticated"])
@pytest.mark.parametrize("table", APP_TABLES)
async def test_client_roles_cannot_read_app_tables(
    conn: AsyncConnection, role: str, table: str
) -> None:
    savepoint = await conn.begin_nested()
    await _as_role(conn, role)
    error = await _fails(conn, f"select * from app.{table} limit 1")
    await savepoint.rollback()
    assert "permission denied" in error


async def _insert_event(conn: AsyncConnection, slug: str) -> str:
    result = await conn.execute(
        text(
            "insert into app.events"
            " (organization_id, slug, name, brand, timezone, starts_on, ends_on)"
            " values (:org, :slug, :slug, 'munych', 'America/Mexico_City',"
            " '2026-01-01', '2026-01-02') returning id"
        ),
        {"org": ORG_ID, "slug": slug},
    )
    return str(result.scalar_one())


async def test_anon_reads_only_published_public_results(conn: AsyncConnection) -> None:
    hidden_event = await _insert_event(conn, "evento-oculto")
    await conn.execute(
        text(
            "insert into public.public_results"
            " (event_slug, event_id, published, version, data) values"
            " ('sd-mun-2026', :published_event, true, 1, '{}'),"
            " ('evento-oculto', :hidden_event, false, 1, '{}')"
        ),
        {"published_event": EVENT_ID, "hidden_event": hidden_event},
    )

    for role in ("anon", "authenticated"):
        savepoint = await conn.begin_nested()
        await _as_role(conn, role)
        slugs = (await conn.execute(text("select event_slug from public.public_results"))).all()
        assert [row[0] for row in slugs] == ["sd-mun-2026"]
        error = await _fails(
            conn, "update public.public_results set published = true where event_slug = 'x'"
        )
        assert "permission denied" in error
        error = await _fails(
            conn,
            "insert into public.public_results (event_slug, event_id, data) values ('x', :e, '{}')",
            {"e": hidden_event},
        )
        assert "permission denied" in error
        await savepoint.rollback()


async def test_result_snapshots_are_insert_only(conn: AsyncConnection) -> None:
    snapshot_id = (
        await conn.execute(
            text(
                "insert into app.result_snapshots (event_id, data) values (:e, '{}') returning id"
            ),
            {"e": EVENT_ID},
        )
    ).scalar_one()
    error = await _fails(
        conn,
        "update app.result_snapshots set data = '{\"x\": 1}' where id = :id",
        {"id": snapshot_id},
    )
    assert "solo inserción" in error
    error = await _fails(
        conn, "delete from app.result_snapshots where id = :id", {"id": snapshot_id}
    )
    assert "solo inserción" in error


async def test_audit_log_is_insert_only(conn: AsyncConnection) -> None:
    audit_id = (
        await conn.execute(
            text(
                "insert into app.audit_log (actor_id, entity, entity_id, action)"
                " values (:a, 'score', gen_random_uuid(), 'create') returning id"
            ),
            {"a": ADMIN_ID},
        )
    ).scalar_one()
    assert "solo inserción" in await _fails(
        conn, "update app.audit_log set action = 'x' where id = :id", {"id": audit_id}
    )
    assert "solo inserción" in await _fails(
        conn, "delete from app.audit_log where id = :id", {"id": audit_id}
    )


async def _hook_claims(conn: AsyncConnection, user_id: str) -> dict[str, Any]:
    savepoint = await conn.begin_nested()
    await _as_role(conn, "supabase_auth_admin")
    event = json.dumps({"user_id": user_id, "claims": {"sub": user_id, "role": "authenticated"}})
    result = await conn.execute(
        text("select public.custom_access_token_hook(cast(:event as jsonb))"), {"event": event}
    )
    value = result.scalar_one()
    await savepoint.rollback()
    payload = json.loads(value) if isinstance(value, str) else value
    claims: dict[str, Any] = payload["claims"]
    return claims


async def test_auth_hook_adds_app_role_claim(conn: AsyncConnection) -> None:
    assert (await _hook_claims(conn, ADMIN_ID))["app_role"] == "admin"
    assert (await _hook_claims(conn, JUDGE_1_ID))["app_role"] == "judge"
    unknown = await _hook_claims(conn, "99999999-0000-4000-8000-000000000000")
    assert "app_role" not in unknown
    assert unknown["role"] == "authenticated"


async def test_auth_hook_omits_role_for_inactive_judge(conn: AsyncConnection) -> None:
    await conn.execute(
        text("update app.judges set active = false where user_id = :id"), {"id": JUDGE_1_ID}
    )
    assert "app_role" not in await _hook_claims(conn, JUDGE_1_ID)


async def test_client_roles_cannot_execute_auth_hook(conn: AsyncConnection) -> None:
    savepoint = await conn.begin_nested()
    await _as_role(conn, "authenticated")
    error = await _fails(
        conn, 'select public.custom_access_token_hook(\'{"user_id": null, "claims": {}}\')'
    )
    await savepoint.rollback()
    assert "permission denied" in error


async def test_seed_loads_sample_event(conn: AsyncConnection) -> None:
    counts = (
        await conn.execute(
            text(
                "select"
                " (select count(*) from app.committees where event_id = :e),"
                " (select count(*) from app.delegations d join app.committees c"
                "   on c.id = d.committee_id where c.event_id = :e),"
                " (select count(*) from app.scoring_sessions s join app.committees c"
                "   on c.id = s.committee_id where c.event_id = :e),"
                " (select count(*) from app.criteria cr join app.events ev"
                "   on ev.default_rubric_id = cr.rubric_id where ev.id = :e),"
                " (select sum(weight) from app.criteria cr join app.events ev"
                "   on ev.default_rubric_id = cr.rubric_id where ev.id = :e),"
                " (select count(distinct cj.judge_id) from app.committee_judges cj"
                "   join app.committees c on c.id = cj.committee_id where c.event_id = :e)"
            ),
            {"e": EVENT_ID},
        )
    ).one()
    assert tuple(counts) == (2, 12, 4, 6, 100, 2)


async def test_storage_bucket_for_event_logos(conn: AsyncConnection) -> None:
    row = (
        await conn.execute(
            text(
                "select public, file_size_limit, allowed_mime_types"
                " from storage.buckets where id = 'event-logos'"
            )
        )
    ).one()
    assert row[0] is True
    assert row[1] == 2 * 1024 * 1024
    assert sorted(row[2]) == ["image/png", "image/svg+xml", "image/webp"]
