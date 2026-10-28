import asyncio
import json
import uuid

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from munych_api.shared.auth import InvalidTokenError, JwtVerifier, SupabaseKeyResolver
from tests.support.auth import PUBLIC_KEY, TEST_ISSUER, TEST_KID, make_test_verifier, make_token

USER_ID = uuid.uuid4()


async def test_valid_token_builds_current_user() -> None:
    user = await make_test_verifier().verify(make_token(USER_ID, role="judge", email="j@x.org"))
    assert user.user_id == USER_ID
    assert user.role == "judge"
    assert user.email == "j@x.org"


async def test_unknown_app_role_is_ignored() -> None:
    user = await make_test_verifier().verify(make_token(USER_ID, role="superadmin"))
    assert user.role is None


async def test_missing_app_role_is_none() -> None:
    user = await make_test_verifier().verify(make_token(USER_ID, role=None))
    assert user.role is None


@pytest.mark.parametrize(
    "token_kwargs",
    [
        {"expires_in": -300},  # fuera de la tolerancia de reloj
        {"audience": "anon"},
        {"issuer": "https://otro-proyecto.supabase.co/auth/v1"},
        {"key": rsa.generate_private_key(public_exponent=65537, key_size=2048)},
        {"kid": "clave-desconocida"},
    ],
    ids=["expirado", "audiencia", "emisor", "firma", "kid"],
)
async def test_invalid_tokens_are_rejected(token_kwargs: dict[str, object]) -> None:
    token = make_token(USER_ID, **token_kwargs)  # type: ignore[arg-type]
    with pytest.raises(InvalidTokenError):
        await make_test_verifier().verify(token)


async def test_issuer_clock_ahead_is_tolerated() -> None:
    # El reloj del servidor de Auth va por delante del nuestro: `iat` queda "en el futuro".
    token = make_token(USER_ID, clock_offset=67)
    assert (await make_test_verifier().verify(token)).user_id == USER_ID


async def test_malformed_and_unsigned_tokens_are_rejected() -> None:
    verifier = make_test_verifier()
    with pytest.raises(InvalidTokenError):
        await verifier.verify("no-es-un-jwt")
    unsigned = jwt.encode(
        {"sub": str(USER_ID), "aud": "authenticated", "iss": TEST_ISSUER, "exp": 9999999999},
        key=None,
        algorithm="none",
    )
    with pytest.raises(InvalidTokenError):
        await verifier.verify(unsigned)


async def test_hs256_secret_fallback() -> None:
    secret = "secreto-heredado-de-al-menos-32-caracteres"
    verifier = JwtVerifier(
        issuer=TEST_ISSUER,
        key_resolver=SupabaseKeyResolver(jwks_url="http://no-usado", hs256_secret=secret),
    )
    token = make_token(USER_ID, key=secret, algorithm="HS256", role="admin")
    assert (await verifier.verify(token)).role == "admin"

    no_secret = JwtVerifier(
        issuer=TEST_ISSUER, key_resolver=SupabaseKeyResolver(jwks_url="http://no-usado")
    )
    with pytest.raises(InvalidTokenError):
        await no_secret.verify(token)


def _jwks(*keys: tuple[str, object, str]) -> dict[str, object]:
    out = []
    for kid, public_key, alg in keys:
        algo = jwt.algorithms.get_default_algorithms()[alg]
        jwk = json.loads(algo.to_jwk(public_key))
        jwk.update({"kid": kid, "alg": alg, "use": "sig"})
        out.append(jwk)
    return {"keys": out}


async def test_jwks_is_fetched_cached_and_refreshed_on_rotation() -> None:
    ec_key = ec.generate_private_key(ec.SECP256R1())
    served = {"jwks": _jwks((TEST_KID, PUBLIC_KEY, "RS256"))}
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json=served["jwks"])

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    resolver = SupabaseKeyResolver(
        jwks_url=f"{TEST_ISSUER}/.well-known/jwks.json",
        http_client=http,
        min_refresh_interval_seconds=0,
    )
    verifier = JwtVerifier(issuer=TEST_ISSUER, key_resolver=resolver)

    await verifier.verify(make_token(USER_ID))
    await verifier.verify(make_token(USER_ID))
    assert calls == [f"{TEST_ISSUER}/.well-known/jwks.json"]

    # Rotación: nueva clave ES256 con otro kid.
    served["jwks"] = _jwks(("nueva", ec_key.public_key(), "ES256"))
    token = make_token(USER_ID, key=ec_key, kid="nueva", algorithm="ES256")
    assert (await verifier.verify(token)).user_id == USER_ID
    assert len(calls) == 2
    await http.aclose()


async def test_concurrent_cold_requests_fetch_jwks_once() -> None:
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        await asyncio.sleep(0.01)
        return httpx.Response(200, json=_jwks((TEST_KID, PUBLIC_KEY, "RS256")))

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    resolver = SupabaseKeyResolver(jwks_url="http://jwks", http_client=http)
    verifier = JwtVerifier(issuer=TEST_ISSUER, key_resolver=resolver)

    await asyncio.gather(*(verifier.verify(make_token(USER_ID)) for _ in range(10)))
    assert len(calls) == 1
    await http.aclose()


async def test_expired_cache_is_used_while_refreshing_in_background() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json=_jwks((TEST_KID, PUBLIC_KEY, "RS256")))

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    resolver = SupabaseKeyResolver(jwks_url="http://jwks", http_client=http, cache_ttl_seconds=0)
    verifier = JwtVerifier(issuer=TEST_ISSUER, key_resolver=resolver)

    await resolver.warm_up()
    assert len(calls) == 1
    # TTL vencido: valida con la clave cacheada y renueva en segundo plano.
    await verifier.verify(make_token(USER_ID))
    await asyncio.sleep(0.01)
    assert len(calls) == 2
    await resolver.aclose()
    await http.aclose()


async def test_jwks_unavailable_rejects_token() -> None:
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(503)))
    resolver = SupabaseKeyResolver(jwks_url="http://jwks", http_client=http)
    with pytest.raises(InvalidTokenError):
        await JwtVerifier(issuer=TEST_ISSUER, key_resolver=resolver).verify(make_token(USER_ID))
    await http.aclose()
