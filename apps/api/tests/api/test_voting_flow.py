"""Votación de un MUN regular de extremo a extremo contra la BD local (ADR-005).

Evento mun_regular → comité con 3 delegaciones → mesa y staff asignados → accesos
de delegados → abrir el voto entre pares → votar premios (sin votar por la propia,
una sola vez) → ranking ponderado por rol.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.support.auth import bearer, make_token
from tests.support.seed import ADMIN_ID

pytestmark = pytest.mark.integration

API = "/api/v1"
ADMIN = bearer(make_token(ADMIN_ID, role="admin"))
LINK = "https://panel.example.mx/#/votar/"


def _ok(response: Any, status: int = 200) -> Any:
    assert response.status_code == status, response.text
    return response.json()


async def _account(client: AsyncClient, slug: str, name: str) -> tuple[str, dict[str, str]]:
    judge = _ok(
        await client.post(
            f"{API}/judges",
            headers=ADMIN,
            json={"email": f"{slug}-{name.lower()}@munych.dev", "full_name": name},
        ),
        201,
    )
    return judge["judge_id"], bearer(make_token(judge["judge_id"], role="judge"))


async def test_mun_regular_voting_flow(client: AsyncClient, engine: AsyncEngine) -> None:
    slug = f"voto-{uuid.uuid4().hex[:8]}"
    event = _ok(
        await client.post(
            f"{API}/events",
            headers=ADMIN,
            json={
                "slug": slug,
                "name": "MUN Regular",
                "brand": "munych",
                "event_type": "mun_regular",
                "timezone": "America/Mexico_City",
                "starts_on": "2026-11-11",
                "ends_on": "2026-11-12",
            },
        ),
        201,
    )
    assert event["event_type"] == "mun_regular"
    event_id = event["id"]
    committee_id = _ok(
        await client.post(
            f"{API}/events/{event_id}/committees",
            headers=ADMIN,
            json={
                "name": "Consejo de Seguridad",
                "acronym": "CS",
                "slug": "cs",
                "type": "security_council",
                "delegation_mode": "single",
                "sessions_count": 2,
            },
        ),
        201,
    )["id"]
    delegations = {}
    for code, person in (("MX", "Ana Pérez"), ("US", "John Smith"), ("FR", "Marie Curie")):
        created = _ok(
            await client.post(
                f"{API}/committees/{committee_id}/delegations",
                headers=ADMIN,
                json={"country_code": code, "delegates": [{"full_name": person}]},
            ),
            201,
        )
        delegations[code] = {"id": created["id"], "delegate": created["delegates"][0]["id"]}

    # Mesa (chair) y staff con cuenta; un "juez" no califica en un MUN regular.
    chair_id, chair = await _account(client, slug, "Mesa")
    staff_id, staff = await _account(client, slug, "Staff")
    judge_id, judge = await _account(client, slug, "Juez")
    _ok(
        await client.put(
            f"{API}/committees/{committee_id}/judges",
            headers=ADMIN,
            json=[
                {"judge_id": chair_id, "role": "chair"},
                {"judge_id": staff_id, "role": "staff"},
                {"judge_id": judge_id, "role": "judge"},
            ],
        )
    )

    # 1. Accesos: se generan una vez; listarlos no devuelve tokens.
    generated = _ok(
        await client.post(
            f"{API}/events/{event_id}/voter-tokens", headers=ADMIN, json={"link_base": LINK}
        ),
        201,
    )
    assert len(generated) == 3
    tokens = {g["country_code"]: g["token"] for g in generated}
    assert all(g["url"] == LINK + g["token"] for g in generated)
    assert all(g["qr_svg"].startswith("<svg") for g in generated)
    again = _ok(
        await client.post(
            f"{API}/events/{event_id}/voter-tokens", headers=ADMIN, json={"link_base": LINK}
        ),
        201,
    )
    assert again == []  # todos tienen un acceso vigente
    listing = _ok(await client.get(f"{API}/events/{event_id}/voter-tokens", headers=ADMIN))
    assert {a["status"] for a in listing} == {"active"}
    assert "token" not in listing[0]

    async with engine.connect() as conn:
        stored = await conn.scalar(
            text("select count(*) from app.voter_tokens where token_hash = :t"),
            {"t": tokens["MX"]},
        )
    assert stored == 0  # en la base solo está el hash

    mx = bearer(tokens["MX"])
    # 2. Boleta entre pares: todas las delegaciones menos la propia; con 2 candidatas
    #    se votan 2 premios. La votación aún no abre (sin programar).
    ballot = _ok(await client.get(f"{API}/vote/ballot", headers=mx))
    assert ballot["own_delegation"]["country_code"] == "MX"
    assert {d["country_code"] for d in ballot["delegations"]} == {"US", "FR"}
    assert ballot["peer_vote"]["status"] == "not_scheduled"
    assert ballot["weight"] == 50.0
    assert [a["award_type"] for a in ballot["awards"]] == ["best_delegate", "outstanding_delegate"]
    assert ballot["picks"] == []
    assert ballot["receipt"] is None

    def picks(best: str, outstanding: str) -> dict[str, Any]:
        return {
            "picks": [
                {"award_type": "best_delegate", "delegation_id": delegations[best]["id"]},
                {
                    "award_type": "outstanding_delegate",
                    "delegation_id": delegations[outstanding]["id"],
                },
            ]
        }

    waiting = await client.post(f"{API}/vote/ballot", headers=mx, json=picks("US", "FR"))
    assert waiting.json()["code"] == "SESSION_CLOSED"

    _ok(await client.patch(f"{API}/events/{event_id}", headers=ADMIN, json={"status": "active"}))
    _ok(await client.post(f"{API}/committees/{committee_id}/sessions/1/open", headers=ADMIN))
    window = _ok(
        await client.put(f"{API}/committees/{committee_id}/peer-vote", headers=ADMIN, json={})
    )
    assert window["status"] == "open"

    # 3. No se vota por la propia delegación, ni dos premios a la misma, ni a medias.
    own = await client.post(f"{API}/vote/ballot", headers=mx, json=picks("MX", "FR"))
    assert (own.status_code, own.json()["code"]) == (403, "FORBIDDEN")
    twice = await client.post(f"{API}/vote/ballot", headers=mx, json=picks("US", "US"))
    assert twice.status_code == 422
    partial = await client.post(
        f"{API}/vote/ballot", headers=mx, json={"picks": picks("US", "FR")["picks"][:1]}
    )
    assert partial.status_code == 422

    voted = _ok(await client.post(f"{API}/vote/ballot", headers=mx, json=picks("US", "FR")))
    assert [p["award_type"] for p in voted["picks"]] == ["best_delegate", "outstanding_delegate"]
    assert voted["receipt"].startswith("CS-")
    # Una vez enviado no se puede cambiar.
    again_vote = await client.post(f"{API}/vote/ballot", headers=mx, json=picks("FR", "US"))
    assert (again_vote.status_code, again_vote.json()["code"]) == (409, "CONFLICT")
    _ok(
        await client.post(
            f"{API}/vote/ballot", headers=bearer(tokens["FR"]), json=picks("US", "MX")
        )
    )
    windows = _ok(await client.get(f"{API}/events/{event_id}/peer-vote", headers=ADMIN))
    assert (windows[0]["voters"], windows[0]["submitted"]) == (3, 2)

    # 4. Defensa en profundidad: el trigger rechaza el voto por la propia delegación
    #    y el voto enviado no se puede modificar.
    async with engine.connect() as conn:
        with pytest.raises(DBAPIError, match="propia delegación"):
            await conn.execute(
                text(
                    "insert into app.peer_votes"
                    " (voter_delegate_id, committee_id, award_type, delegation_id)"
                    " values (:v, :c, 'honorable_mention', :d)"
                ),
                {
                    "v": delegations["US"]["delegate"],
                    "c": committee_id,
                    "d": delegations["US"]["id"],
                },
            )
    async with engine.connect() as conn:
        with pytest.raises(DBAPIError, match="solo inserción"):
            await conn.execute(
                text("update app.peer_votes set delegation_id = delegation_id where true")
            )

    # Cerrar: ya no se vota.
    closed = _ok(
        await client.post(f"{API}/committees/{committee_id}/peer-vote/close", headers=ADMIN)
    )
    assert closed["status"] == "closed"
    late = await client.post(
        f"{API}/vote/ballot", headers=bearer(tokens["US"]), json=picks("MX", "FR")
    )
    assert late.json()["code"] == "SESSION_CLOSED"

    # 5. Mesa y staff califican con el flujo de siempre; el juez queda rechazado.
    session_id = _ok(await client.get(f"{API}/committees/{committee_id}/sessions", headers=ADMIN))[
        0
    ]["id"]
    rubric = _ok(await client.get(f"{API}/events/{event_id}/rubrics", headers=ADMIN))[0]
    criteria = [c["id"] for c in rubric["criteria"]]

    def batch(value: int) -> dict[str, Any]:
        return {
            "items": [
                {
                    "client_id": str(uuid.uuid4()),
                    "delegate_id": delegations[code]["delegate"],
                    "session_id": session_id,
                    "criterion_id": c,
                    "value": value,
                    "client_updated_at": datetime.now(UTC).isoformat(),
                }
                for code in ("MX", "US", "FR")
                for c in criteria
            ]
        }

    assert not _ok(await client.post(f"{API}/judge/scores/batch", headers=chair, json=batch(4)))[
        "rejected"
    ]
    assert not _ok(await client.post(f"{API}/judge/scores/batch", headers=staff, json=batch(2)))[
        "rejected"
    ]
    rejected = _ok(await client.post(f"{API}/judge/scores/batch", headers=judge, json=batch(1)))
    assert {r["code"] for r in rejected["rejected"]} == {"FORBIDDEN"}

    # 6. Ranking ponderado: mesa 30 %, delegados 50 %, staff 20 % (escala 1-4).
    ranking = _ok(await client.get(f"{API}/committees/{committee_id}/ranking", headers=ADMIN))
    assert ranking["event_type"] == "mun_regular"
    assert ranking["role_weights"] == {"chair": 30.0, "delegate": 50.0, "staff": 20.0}
    by_code = {e["country_code"]: e for e in ranking["items"]}
    # Pares (2 votantes, máx. 6 puntos): US 3+3 = 100; MX 2 y FR 2 = 33.33.
    # US: 30·100 + 50·100 + 20·50 = 90
    assert by_code["US"]["role_scores"] == {"chair": 100.0, "delegate": 100.0, "staff": 50.0}
    assert by_code["US"]["score"] == 90.0
    # MX: 30·100 + 50·33.33 + 20·50 = 56.67
    assert by_code["MX"]["role_scores"]["delegate"] == 33.33
    assert by_code["MX"]["score"] == 56.67
    assert ranking["items"][0]["country_code"] == "US"

    # 7. Revocar: el acceso deja de servir de inmediato.
    revoked = _ok(
        await client.post(
            f"{API}/events/{event_id}/voter-tokens/revoke",
            headers=ADMIN,
            json={"delegate_ids": [delegations["MX"]["delegate"]]},
        )
    )
    assert revoked == {"revoked": 1}
    denied = await client.get(f"{API}/vote/ballot", headers=mx)
    assert (denied.status_code, denied.json()["code"]) == (401, "UNAUTHORIZED")
    garbage = await client.get(f"{API}/vote/ballot", headers=bearer("x" * 32))
    assert garbage.status_code == 401
    assert (await client.get(f"{API}/vote/ballot")).status_code == 401

    # 8. Regenerar para un delegado concreto da un token nuevo y válido.
    (fresh,) = _ok(
        await client.post(
            f"{API}/events/{event_id}/voter-tokens",
            headers=ADMIN,
            json={"link_base": LINK, "delegate_ids": [delegations["MX"]["delegate"]]},
        ),
        201,
    )
    assert fresh["token"] != tokens["MX"]
    _ok(await client.get(f"{API}/vote/ballot", headers=bearer(fresh["token"])))


async def test_judges_only_event_has_no_voter_tokens(client: AsyncClient) -> None:
    slug = f"jueces-{uuid.uuid4().hex[:8]}"
    event = _ok(
        await client.post(
            f"{API}/events",
            headers=ADMIN,
            json={
                "slug": slug,
                "name": "Solo jueces",
                "brand": "munych",
                "timezone": "America/Mexico_City",
                "starts_on": "2026-11-11",
                "ends_on": "2026-11-12",
            },
        ),
        201,
    )
    response = await client.post(
        f"{API}/events/{event['id']}/voter-tokens", headers=ADMIN, json={"link_base": LINK}
    )
    assert (response.status_code, response.json()["code"]) == (409, "CONFLICT")
    bad_link = await client.post(
        f"{API}/events/{event['id']}/voter-tokens",
        headers=ADMIN,
        json={"link_base": "http://inseguro.mx/#/votar/"},
    )
    assert bad_link.status_code == 422
