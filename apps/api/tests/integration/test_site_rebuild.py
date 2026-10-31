"""Reconstrucción agrupada del sitio público (migración site_rebuild)."""

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from munych_api.modules.results.infrastructure.pages_rebuild import PagesRebuildScheduler
from tests.integration.conftest import EVENT_ID

pytestmark = pytest.mark.integration

HOOK_URL = "http://127.0.0.1:9/hook-de-prueba"


async def _state(conn: AsyncConnection) -> Any:
    return (await conn.execute(text("select * from app.site_rebuild"))).one()


async def _publish(conn: AsyncConnection) -> None:
    await conn.execute(
        text(
            "insert into public.public_results (event_slug, event_id, published, version, data)"
            " values ('sd-mun-2026', :e, true, 1, '{}')"
            " on conflict (event_id) do update set version = public_results.version + 1"
        ),
        {"e": EVENT_ID},
    )


async def _set_hook(conn: AsyncConnection, url: str) -> None:
    """Dentro de la transacción de la prueba (se deshace al terminar)."""
    await conn.execute(text("delete from vault.secrets where name = 'pages_deploy_hook_url'"))
    if url:
        await conn.execute(
            text("select vault.create_secret(:url, 'pages_deploy_hook_url')"), {"url": url}
        )


async def _reset(conn: AsyncConnection) -> None:
    await conn.execute(
        text("update app.site_rebuild set pending_since = null, last_change_at = null")
    )


async def test_change_in_public_results_marks_rebuild_pending(conn: AsyncConnection) -> None:
    await _reset(conn)
    await _publish(conn)
    state = await _state(conn)
    assert state.pending_since is not None
    assert state.last_change_at is not None


async def test_dispatch_waits_for_quiet_period(conn: AsyncConnection) -> None:
    await _reset(conn)
    await _set_hook(conn, HOOK_URL)
    await _publish(conn)
    # El cambio es de "ahora": dentro de los 45 s de espera no se llama al hook.
    assert await conn.scalar(text("select app.dispatch_site_rebuild()")) is False
    assert (await _state(conn)).pending_since is not None


async def test_dispatch_calls_hook_once_after_quiet_period(conn: AsyncConnection) -> None:
    await _reset(conn)
    await _set_hook(conn, HOOK_URL)
    await _publish(conn)
    await _publish(conn)
    dispatched = await conn.scalar(text("select app.dispatch_site_rebuild(interval '0 seconds')"))
    assert dispatched is True
    state = await _state(conn)
    assert state.pending_since is None
    assert state.last_request_id is not None
    # Dos cambios, un solo build: ya no queda nada pendiente.
    assert (
        await conn.scalar(text("select app.dispatch_site_rebuild(interval '0 seconds')")) is False
    )


async def test_dispatch_keeps_changes_pending_without_hook(conn: AsyncConnection) -> None:
    await _reset(conn)
    await _set_hook(conn, "")
    await _publish(conn)
    assert (
        await conn.scalar(text("select app.dispatch_site_rebuild(interval '0 seconds')")) is False
    )
    assert (await _state(conn)).pending_since is not None


async def test_cron_job_is_scheduled(conn: AsyncConnection) -> None:
    schedule = await conn.scalar(
        text("select schedule from cron.job where jobname = 'site-rebuild'")
    )
    assert schedule == "30 seconds"


async def test_scheduler_reports_whether_hook_is_configured(conn: AsyncConnection) -> None:
    # PagesRebuildScheduler solo usa `scalar`, que AsyncConnection también tiene.
    scheduler = PagesRebuildScheduler(conn)  # type: ignore[arg-type]
    await _set_hook(conn, "")
    assert await scheduler.revalidate("sd-mun-2026") is False
    await _set_hook(conn, HOOK_URL)
    assert await scheduler.revalidate("sd-mun-2026") is True
