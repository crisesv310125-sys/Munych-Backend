"""Cliente de Supabase con la clave `service_role` (solo backend).

Se expone detrás de dos puertos pequeños (`AuthAdmin` y `ObjectStorage`) para
poder sustituirlo por dobles en las pruebas. La clave nunca se registra en logs.
"""

from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from munych_api.config import Settings
from munych_api.shared.kernel import DomainError, ErrorCode

if TYPE_CHECKING:
    from supabase import AsyncClient


class AuthAdmin(Protocol):
    async def invite_user_by_email(self, email: str, *, redirect_to: str | None = None) -> UUID:
        """Envía la invitación y devuelve el id del usuario creado."""
        ...


class ObjectStorage(Protocol):
    async def upload(self, bucket: str, path: str, content: bytes, content_type: str) -> None: ...

    def public_url(self, bucket: str, path: str) -> str: ...


def public_object_url(supabase_url: str, bucket: str, path: str) -> str:
    return f"{supabase_url.rstrip('/')}/storage/v1/object/public/{bucket}/{path}"


class SupabaseAdmin:
    """Implementa `AuthAdmin` y `ObjectStorage` con supabase-py (cliente async perezoso)."""

    def __init__(self, settings: Settings) -> None:
        self._url = settings.supabase_url
        self._key = settings.supabase_service_role_key
        self._client: AsyncClient | None = None

    async def _get_client(self) -> "AsyncClient":
        if self._client is None:
            from supabase import acreate_client  # noqa: PLC0415 — solo si se usa

            self._client = await acreate_client(self._url, self._key.get_secret_value())
        return self._client

    async def invite_user_by_email(self, email: str, *, redirect_to: str | None = None) -> UUID:
        from supabase_auth.errors import AuthApiError  # noqa: PLC0415 — solo si se usa

        client = await self._get_client()
        options: dict[str, Any] = {"redirect_to": redirect_to} if redirect_to else {}
        try:
            response = await client.auth.admin.invite_user_by_email(email, options)  # type: ignore[arg-type]
        except AuthApiError as exc:
            # El SMTP integrado de Supabase permite pocos correos por hora.
            if exc.status == 429:
                raise DomainError(
                    ErrorCode.RATE_LIMITED,
                    "Supabase limitó el envío de correos; espera unos minutos e inténtalo de nuevo",
                ) from exc
            if exc.status == 422:
                raise DomainError(
                    ErrorCode.CONFLICT, "Ese correo ya tiene una cuenta confirmada"
                ) from exc
            raise
        if response.user is None:  # pragma: no cover — respuesta anómala de GoTrue
            raise RuntimeError("Supabase no devolvió el usuario invitado")
        return UUID(str(response.user.id))

    async def upload(self, bucket: str, path: str, content: bytes, content_type: str) -> None:
        client = await self._get_client()
        await client.storage.from_(bucket).upload(
            path, content, {"content-type": content_type, "upsert": "true"}
        )

    def public_url(self, bucket: str, path: str) -> str:
        return public_object_url(self._url, bucket, path)
