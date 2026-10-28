"""JWT de prueba firmados con una clave RSA local (sección 8.1)."""

import time
from typing import Any
from uuid import UUID

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from munych_api.shared.auth import JwtVerifier

TEST_ISSUER = "http://127.0.0.1:54321/auth/v1"
TEST_KID = "test-key"

_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PUBLIC_KEY = _private_key.public_key()


class StaticKeyResolver:
    def __init__(self, keys: dict[str | None, Any]) -> None:
        self._keys = keys

    async def resolve(self, kid: str | None, algorithm: str) -> Any:
        from munych_api.shared.auth import InvalidTokenError

        if kid not in self._keys:
            raise InvalidTokenError("Clave de firma desconocida")
        return self._keys[kid]


def make_test_verifier() -> JwtVerifier:
    return JwtVerifier(issuer=TEST_ISSUER, key_resolver=StaticKeyResolver({TEST_KID: PUBLIC_KEY}))


def make_token(
    user_id: UUID | str,
    *,
    role: str | None = "admin",
    email: str | None = "usuario@munych.dev",
    expires_in: int = 3600,
    audience: str = "authenticated",
    issuer: str = TEST_ISSUER,
    key: Any = None,
    kid: str = TEST_KID,
    algorithm: str = "RS256",
    clock_offset: int = 0,
) -> str:
    now = int(time.time()) + clock_offset
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "aud": audience,
        "iss": issuer,
        "iat": now,
        "exp": now + expires_in,
        "role": "authenticated",
    }
    if email is not None:
        claims["email"] = email
    if role is not None:
        claims["app_role"] = role
    return jwt.encode(
        claims, key if key is not None else _private_key, algorithm=algorithm, headers={"kid": kid}
    )


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
