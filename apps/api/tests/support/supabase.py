"""Dobles de los puertos de Supabase (`AuthAdmin` y `ObjectStorage`)."""

import uuid
from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from munych_api.shared.supabase import public_object_url


class FakeSupabase:
    """Registra invitaciones y subidas. Si recibe un engine, crea el usuario en `auth.users`."""

    def __init__(self, engine: AsyncEngine | None = None) -> None:
        self._engine = engine
        self.invited: list[str] = []
        self.invite_redirects: list[str | None] = []
        self.invite_data: list[dict[str, str] | None] = []
        self.metadata_updates: list[tuple[UUID, dict[str, str]]] = []
        self.uploads: dict[tuple[str, str], tuple[bytes, str]] = {}

    async def invite_user_by_email(
        self,
        email: str,
        *,
        redirect_to: str | None = None,
        data: Mapping[str, str] | None = None,
    ) -> UUID:
        self.invited.append(email)
        self.invite_redirects.append(redirect_to)
        self.invite_data.append(dict(data) if data is not None else None)
        user_id = uuid.uuid4()
        if self._engine is not None:
            async with self._engine.begin() as conn:
                # Como GoTrue: reinvitar a un usuario sin confirmar lo reutiliza.
                existing = await conn.scalar(
                    text(
                        "update auth.users set invited_at = now() where email = :email returning id"
                    ),
                    {"email": email},
                )
                if existing is not None:
                    return UUID(str(existing))
                await conn.execute(
                    text(
                        "insert into auth.users (id, aud, role, email, invited_at)"
                        " values (:id, 'authenticated', 'authenticated', :email, now())"
                    ),
                    {"id": user_id, "email": email},
                )
        return user_id

    async def update_user_metadata(self, user_id: UUID, data: Mapping[str, str]) -> None:
        self.metadata_updates.append((user_id, dict(data)))

    async def upload(self, bucket: str, path: str, content: bytes, content_type: str) -> None:
        self.uploads[(bucket, path)] = (content, content_type)

    def public_url(self, bucket: str, path: str) -> str:
        return public_object_url("http://127.0.0.1:54321", bucket, path)


class FakeRevalidator:
    """Doble del webhook de revalidación: registra los slugs avisados."""

    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.calls: list[str] = []

    async def revalidate(self, event_slug: str) -> bool:
        self.calls.append(event_slug)
        return self.ok
