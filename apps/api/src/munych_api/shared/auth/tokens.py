"""Verificación de los JWT de Supabase Auth (JWKS, con HS256 heredado como alternativa)."""

import asyncio
import contextlib
import time
from dataclasses import dataclass
from typing import Any, Literal, Protocol, get_args
from uuid import UUID

import httpx
import jwt
import structlog

Role = Literal["admin", "judge"]
ROLES: tuple[str, ...] = get_args(Role)

ASYMMETRIC_ALGORITHMS = frozenset({"RS256", "ES256", "EdDSA"})
SYMMETRIC_ALGORITHMS = frozenset({"HS256"})

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class CurrentUser:
    user_id: UUID
    email: str | None
    role: Role | None


class InvalidTokenError(Exception):
    """El token no es válido (firma, expiración, audiencia, emisor o forma)."""


class TokenVerifier(Protocol):
    async def verify(self, token: str) -> CurrentUser: ...


class KeyResolver(Protocol):
    async def resolve(self, kid: str | None, algorithm: str) -> Any: ...


class JwtVerifier:
    """Valida firma, `exp`, `aud = authenticated` e `iss`, y construye `CurrentUser`."""

    def __init__(
        self,
        *,
        issuer: str,
        key_resolver: KeyResolver,
        audience: str = "authenticated",
        leeway_seconds: float = 120,
    ) -> None:
        self._issuer = issuer
        self._audience = audience
        self._keys = key_resolver
        # Tolerancia de reloj: si el reloj de esta máquina va atrasado respecto a Supabase Auth,
        # el `iat` del token parece "en el futuro" y PyJWT lo rechazaría.
        self._leeway = leeway_seconds

    async def verify(self, token: str) -> CurrentUser:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise InvalidTokenError("Token mal formado") from exc

        algorithm = header.get("alg")
        if algorithm not in ASYMMETRIC_ALGORITHMS | SYMMETRIC_ALGORITHMS:
            raise InvalidTokenError("Algoritmo no permitido")

        key = await self._keys.resolve(header.get("kid"), algorithm)
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key=key,
                algorithms=[algorithm],
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": ["exp", "sub", "aud", "iss"]},
            )
            user_id = UUID(str(claims["sub"]))
        except (jwt.PyJWTError, ValueError) as exc:
            # Solo el tipo y el mensaje de PyJWT: nunca el token ni sus claims.
            logger.info("jwt_rejected", error_type=type(exc).__name__, reason=str(exc))
            raise InvalidTokenError(str(exc)) from exc

        raw_role = claims.get("app_role")
        role: Role | None = raw_role if raw_role in ROLES else None
        email = claims.get("email")
        return CurrentUser(
            user_id=user_id, email=email if isinstance(email, str) else None, role=role
        )


class SupabaseKeyResolver:
    """Descarga y cachea el JWKS del proyecto; admite el secreto HS256 heredado.

    Para no penalizar las peticiones (sobre todo la primera tras el login):
    - `warm_up()` descarga el JWKS al arrancar la app.
    - El cliente HTTP es persistente (sin un handshake TLS nuevo en cada descarga).
    - Al caducar el TTL se siguen usando las claves cacheadas y se refresca en segundo plano.
    - Un candado evita descargas simultáneas cuando llegan varias peticiones a la vez.
    """

    def __init__(
        self,
        *,
        jwks_url: str,
        hs256_secret: str | None = None,
        cache_ttl_seconds: float = 600,
        min_refresh_interval_seconds: float = 30,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._jwks_url = jwks_url
        self._secret = hs256_secret
        self._ttl = cache_ttl_seconds
        self._min_refresh = min_refresh_interval_seconds
        self._http = http_client
        self._owns_http = http_client is None
        self._keys: dict[str | None, Any] = {}
        self._fetched_at = 0.0
        self._generation = 0
        self._lock = asyncio.Lock()
        self._background: asyncio.Task[None] | None = None

    async def warm_up(self) -> None:
        """Descarga el JWKS por adelantado; si falla, se reintentará con la primera petición."""
        with contextlib.suppress(InvalidTokenError):
            await self._refresh()

    async def aclose(self) -> None:
        if self._background is not None:
            self._background.cancel()
        if self._owns_http and self._http is not None:
            await self._http.aclose()
            self._http = None

    async def resolve(self, kid: str | None, algorithm: str) -> Any:
        if algorithm in SYMMETRIC_ALGORITHMS:
            if not self._secret:
                raise InvalidTokenError("El proyecto no acepta tokens HS256")
            return self._secret

        age = time.monotonic() - self._fetched_at
        if not self._keys:
            await self._refresh()
        elif kid not in self._keys and age > self._min_refresh:
            # Posible rotación de claves: refresca una vez (con límite de frecuencia).
            await self._refresh()
        elif age > self._ttl:
            # Claves vigentes pero viejas: se usan ya y se renuevan sin bloquear la petición.
            self._schedule_background_refresh()

        key = self._keys.get(kid)
        if key is None and kid is None and len(self._keys) == 1:
            key = next(iter(self._keys.values()))
        if key is None:
            raise InvalidTokenError("Clave de firma desconocida")
        return key

    def _schedule_background_refresh(self) -> None:
        if self._background is None or self._background.done():
            self._background = asyncio.create_task(self._refresh())

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=5)
        return self._http

    async def _refresh(self) -> None:
        generation = self._generation
        async with self._lock:
            if self._generation != generation:
                return  # Otra petición ya lo refrescó mientras esperábamos el candado.
            try:
                response = await self._client().get(self._jwks_url)
                response.raise_for_status()
                jwk_set = jwt.PyJWKSet.from_dict(response.json())
            except (httpx.HTTPError, jwt.PyJWTError, ValueError) as exc:
                logger.warning("jwks_fetch_failed", error_type=type(exc).__name__)
                if not self._keys:
                    raise InvalidTokenError("No se pudo obtener el JWKS") from exc
                return
            self._keys = {jwk.key_id: jwk.key for jwk in jwk_set.keys}
            self._fetched_at = time.monotonic()
            self._generation += 1
