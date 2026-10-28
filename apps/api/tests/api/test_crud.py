"""CRUD de eventos, comités, delegaciones, delegados, rúbricas y asignaciones (hito 4)."""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from tests.support.auth import bearer, make_token
from tests.support.seed import ADMIN_ID, DISEC_ID, JUDGE_1_ID, JUDGE_2_ID
from tests.support.supabase import FakeSupabase

pytestmark = pytest.mark.integration

ADMIN = bearer(make_token(ADMIN_ID, role="admin"))
JUDGE_1 = bearer(make_token(JUDGE_1_ID, role="judge"))
API = "/api/v1"


def _slug(prefix: str = "evento") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


async def _create_event(client: AsyncClient, **overrides: Any) -> dict[str, Any]:
    body = {
        "slug": _slug(),
        "name": "Evento de prueba",
        "brand": "munych",
        "venue": "CDMX",
        "country_code": "MX",
        "timezone": "America/Mexico_City",
        "starts_on": "2026-11-01",
        "ends_on": "2026-11-02",
        **overrides,
    }
    response = await client.post(f"{API}/events", headers=ADMIN, json=body)
    assert response.status_code == 201, response.text
    event: dict[str, Any] = response.json()
    return event


async def _create_committee(client: AsyncClient, event_id: str, **overrides: Any) -> dict[str, Any]:
    body = {
        "name": "Asamblea General",
        "acronym": "AG",
        "slug": _slug("ag"),
        "type": "general_assembly",
        "delegation_mode": "single",
        "sessions_count": 3,
        **overrides,
    }
    response = await client.post(f"{API}/events/{event_id}/committees", headers=ADMIN, json=body)
    assert response.status_code == 201, response.text
    committee: dict[str, Any] = response.json()
    return committee


# ---------------------------------------------------------------- eventos


async def test_create_event_creates_default_rubric(client: AsyncClient) -> None:
    event = await _create_event(client)
    assert event["status"] == "draft"
    assert event["logo_url"] is None

    rubrics = (await client.get(f"{API}/events/{event['id']}/rubrics", headers=ADMIN)).json()
    assert len(rubrics) == 1
    assert rubrics[0]["id"] == event["default_rubric_id"]
    assert [c["weight"] for c in rubrics[0]["criteria"]] == [20, 20, 20, 15, 15, 10]


async def test_event_validation_and_conflicts(client: AsyncClient) -> None:
    event = await _create_event(client)
    duplicate = await client.post(
        f"{API}/events",
        headers=ADMIN,
        json={
            **{k: event[k] for k in ("slug", "name", "brand", "timezone")},
            "starts_on": "2026-01-01",
            "ends_on": "2026-01-01",
        },
    )
    assert duplicate.status_code == 409

    bad_dates = await client.patch(
        f"{API}/events/{event['id']}", headers=ADMIN, json={"ends_on": "2020-01-01"}
    )
    assert bad_dates.status_code == 422
    assert bad_dates.json()["code"] == "VALIDATION_ERROR"

    bad_tz = await client.patch(
        f"{API}/events/{event['id']}", headers=ADMIN, json={"timezone": "Marte/Olympus"}
    )
    assert bad_tz.status_code == 422


async def test_list_update_and_delete_event(client: AsyncClient) -> None:
    event = await _create_event(client)
    page = (await client.get(f"{API}/events?limit=200", headers=ADMIN)).json()
    assert event["id"] in [e["id"] for e in page["items"]]
    assert page["total"] >= 2

    updated = await client.patch(
        f"{API}/events/{event['id']}",
        headers=ADMIN,
        json={"name": "Renombrado", "status": "active"},
    )
    assert updated.json()["name"] == "Renombrado"
    assert (await client.delete(f"{API}/events/{event['id']}", headers=ADMIN)).status_code == 409

    await client.patch(f"{API}/events/{event['id']}", headers=ADMIN, json={"status": "draft"})
    assert (await client.delete(f"{API}/events/{event['id']}", headers=ADMIN)).status_code == 204
    assert (await client.get(f"{API}/events/{event['id']}", headers=ADMIN)).status_code == 404


async def test_judge_cannot_use_admin_endpoints(client: AsyncClient) -> None:
    response = await client.get(f"{API}/events", headers=JUDGE_1)
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


async def test_upload_logo(client: AsyncClient, fake_supabase: FakeSupabase) -> None:
    event = await _create_event(client)
    url = f"{API}/events/{event['id']}/logo"

    ok = await client.post(url, headers=ADMIN, files={"file": ("l.png", b"\x89PNG", "image/png")})
    assert ok.status_code == 200, ok.text
    assert ok.json()["logo_url"].startswith("http://127.0.0.1:54321/storage/v1/object/public/")
    ((bucket, path),) = fake_supabase.uploads
    assert bucket == "event-logos"
    assert path.startswith(f"{event['id']}/logo-")

    wrong_type = await client.post(
        url, headers=ADMIN, files={"file": ("l.gif", b"GIF8", "image/gif")}
    )
    assert wrong_type.status_code == 422
    too_big = await client.post(
        url, headers=ADMIN, files={"file": ("l.png", b"0" * (2 * 1024 * 1024 + 1), "image/png")}
    )
    assert too_big.status_code == 422


# ---------------------------------------------------------------- comités y sesiones


async def test_committee_defaults_and_sessions(client: AsyncClient) -> None:
    event = await _create_event(client)
    committee = await _create_committee(client, event["id"], type="security_council")
    assert committee["award_quotas"] == {
        "best_delegate": 1,
        "outstanding_delegate": 1,
        "honorable_mention": 2,
        "verbal_commendation": 2,
    }

    patched = await client.patch(
        f"{API}/committees/{committee['id']}",
        headers=ADMIN,
        json={"sessions_count": 5, "award_quotas": {"honorable_mention": 4}},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["sessions_count"] == 5
    assert patched.json()["award_quotas"]["honorable_mention"] == 4
    assert patched.json()["award_quotas"]["best_delegate"] == 1

    duplicate = await client.post(
        f"{API}/events/{event['id']}/committees",
        headers=ADMIN,
        json={
            "name": "Otro",
            "acronym": "O",
            "slug": committee["slug"],
            "type": "crisis",
            "delegation_mode": "single",
            "sessions_count": 1,
        },
    )
    assert duplicate.status_code == 409

    invalid = await client.post(
        f"{API}/events/{event['id']}/committees",
        headers=ADMIN,
        json={
            "name": "X",
            "acronym": "X",
            "slug": "x",
            "type": "crisis",
            "delegation_mode": "single",
            "sessions_count": 21,
        },
    )
    assert invalid.status_code == 422

    assert (
        await client.delete(f"{API}/committees/{committee['id']}", headers=ADMIN)
    ).status_code == 204


# ---------------------------------------------------------------- delegaciones y delegados


async def test_delegations_and_delegates_limits(client: AsyncClient) -> None:
    event = await _create_event(client)
    single = await _create_committee(client, event["id"])
    url = f"{API}/committees/{single['id']}/delegations"

    created = await client.post(
        url,
        headers=ADMIN,
        json={"country_code": "MX", "institution": "Colegio", "delegates": [{"full_name": "Ana"}]},
    )
    assert created.status_code == 201, created.text
    delegation = created.json()
    assert delegation["delegates"][0]["institution"] == "Colegio"

    too_many = await client.post(
        f"{API}/delegations/{delegation['id']}/delegates", headers=ADMIN, json={"full_name": "Bea"}
    )
    assert too_many.status_code == 422
    assert too_many.json()["code"] == "DELEGATES_LIMIT_EXCEEDED"

    repeated = await client.post(url, headers=ADMIN, json={"country_code": "MX"})
    assert repeated.status_code == 409

    both = await client.post(url, headers=ADMIN, json={"country_code": "US", "character_name": "X"})
    assert both.status_code == 422

    renamed = await client.patch(
        f"{API}/delegates/{delegation['delegates'][0]['id']}",
        headers=ADMIN,
        json={"full_name": "  Ana María  "},
    )
    assert renamed.json()["full_name"] == "Ana María"

    to_character = await client.patch(
        f"{API}/delegations/{delegation['id']}",
        headers=ADMIN,
        json={"country_code": None, "character_name": "Ministra"},
    )
    assert to_character.status_code == 200
    assert to_character.json()["character_name"] == "Ministra"

    listing = (await client.get(url, headers=ADMIN)).json()
    assert listing["total"] == 1
    assert listing["items"][0]["delegates"][0]["full_name"] == "Ana María"

    delegate_id = delegation["delegates"][0]["id"]
    assert (await client.delete(f"{API}/delegates/{delegate_id}", headers=ADMIN)).status_code == 204
    assert (
        await client.delete(f"{API}/delegations/{delegation['id']}", headers=ADMIN)
    ).status_code == 204


async def test_double_committee_cannot_become_single_with_pairs(client: AsyncClient) -> None:
    event = await _create_event(client)
    double = await _create_committee(client, event["id"], delegation_mode="double")
    await client.post(
        f"{API}/committees/{double['id']}/delegations",
        headers=ADMIN,
        json={"country_code": "MX", "delegates": [{"full_name": "A"}, {"full_name": "B"}]},
    )
    response = await client.patch(
        f"{API}/committees/{double['id']}", headers=ADMIN, json={"delegation_mode": "single"}
    )
    assert response.status_code == 422
    assert response.json()["code"] == "DELEGATES_LIMIT_EXCEEDED"


async def test_import_csv(client: AsyncClient) -> None:
    event = await _create_event(client)
    committee = await _create_committee(client, event["id"])
    await client.post(
        f"{API}/committees/{committee['id']}/delegations",
        headers=ADMIN,
        json={"country_code": "FR"},
    )
    csv_body = (
        "country_code,character_name,institution,delegate_1,delegate_2\n"
        "MX,,Colegio Ejemplo,Ana Pérez López,\n"
        "US,,Instituto Norte,John Smith,Mary Jones\n"
        ",Ministro de Defensa,Colegio Sur,Luis Gómez,\n"
        "FR,,Liceo,Camille,\n"
        "MX,,Repetido,Otro,\n"
        "XYZ,,Mal,Nadie,\n"
    )
    response = await client.post(
        f"{API}/committees/{committee['id']}/delegations/import",
        headers=ADMIN,
        files={"file": ("d.csv", csv_body.encode(), "text/csv")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["created"] == 2
    assert body["skipped"] == 2
    assert [e["row"] for e in body["errors"]] == [3, 7]

    listing = (
        await client.get(f"{API}/committees/{committee['id']}/delegations", headers=ADMIN)
    ).json()
    assert listing["total"] == 3


# ---------------------------------------------------------------- rúbricas


async def test_replace_rubric_validates_weights(client: AsyncClient) -> None:
    event = await _create_event(client)
    rubric_id = event["default_rubric_id"]
    rubric = (await client.get(f"{API}/rubrics/{rubric_id}", headers=ADMIN)).json()

    bad = await client.put(
        f"{API}/rubrics/{rubric_id}",
        headers=ADMIN,
        json={**rubric, "criteria": [{"name": "Único", "weight": 90}]},
    )
    assert bad.status_code == 422
    assert bad.json()["code"] == "WEIGHTS_MUST_SUM_100"

    kept = rubric["criteria"][0]
    good = await client.put(
        f"{API}/rubrics/{rubric_id}",
        headers=ADMIN,
        json={
            "name": "Rúbrica corta",
            "scale_min": 1,
            "scale_max": 5,
            "criteria": [
                {"id": kept["id"], "name": kept["name"], "weight": 60},
                {"name": "Nuevo", "weight": 40, "level_descriptors": {"5": "Sobresaliente"}},
            ],
        },
    )
    assert good.status_code == 200, good.text
    body = good.json()
    assert body["scale_max"] == 5
    assert [(c["name"], c["weight"], c["position"]) for c in body["criteria"]] == [
        (kept["name"], 60, 1),
        ("Nuevo", 40, 2),
    ]
    assert body["criteria"][0]["id"] == kept["id"]


async def test_committee_rubric_override(client: AsyncClient) -> None:
    event = await _create_event(client)
    extra = await client.post(
        f"{API}/events/{event['id']}/rubrics",
        headers=ADMIN,
        json={
            "name": "Crisis",
            "scale_min": 0,
            "scale_max": 10,
            "criteria": [{"name": "Gestión de crisis", "weight": 100}],
        },
    )
    assert extra.status_code == 201, extra.text
    committee = await _create_committee(client, event["id"], rubric_id=extra.json()["id"])
    assert committee["rubric_id"] == extra.json()["id"]

    other_event = await _create_event(client)
    foreign = await client.post(
        f"{API}/events/{other_event['id']}/committees",
        headers=ADMIN,
        json={
            "name": "X",
            "acronym": "X",
            "slug": "x",
            "type": "crisis",
            "delegation_mode": "single",
            "sessions_count": 1,
            "rubric_id": extra.json()["id"],
        },
    )
    assert foreign.status_code == 404


# ---------------------------------------------------------------- asignaciones


async def test_replace_committee_judges(client: AsyncClient) -> None:
    event = await _create_event(client)
    committee = await _create_committee(client, event["id"])
    url = f"{API}/committees/{committee['id']}/judges"

    response = await client.put(
        url,
        headers=ADMIN,
        json=[{"judge_id": JUDGE_1_ID, "role": "chair"}, {"judge_id": JUDGE_2_ID}],
    )
    assert response.status_code == 200, response.text
    assert {(a["judge_id"], a["role"]) for a in response.json()} == {
        (JUDGE_1_ID, "chair"),
        (JUDGE_2_ID, "judge"),
    }

    replaced = await client.put(url, headers=ADMIN, json=[{"judge_id": JUDGE_2_ID}])
    assert [a["judge_id"] for a in replaced.json()] == [JUDGE_2_ID]
    assert [a["judge_id"] for a in (await client.get(url, headers=ADMIN)).json()] == [JUDGE_2_ID]

    unknown = await client.put(url, headers=ADMIN, json=[{"judge_id": str(uuid.uuid4())}])
    assert unknown.status_code == 404
    repeated = await client.put(
        url, headers=ADMIN, json=[{"judge_id": JUDGE_2_ID}, {"judge_id": JUDGE_2_ID}]
    )
    assert repeated.status_code == 422


async def test_judges_are_scoped_per_event(
    client: AsyncClient, fake_supabase: FakeSupabase
) -> None:
    async def event_judges(event_id: str, path: str = "judges") -> set[str]:
        response = await client.get(f"{API}/{path}?event_id={event_id}&limit=200", headers=ADMIN)
        assert response.status_code == 200, response.text
        return {item["judge_id"] for item in response.json()["items"]}

    event = await _create_event(client)
    assert await event_judges(event["id"]) == set()

    # Un juez existente se suma al evento al invitarlo con `event_id`, sin reenviar correo.
    reused = await client.post(
        f"{API}/judges",
        headers=ADMIN,
        json={"email": "juez1@munych.dev", "full_name": "Laura Méndez", "event_id": event["id"]},
    )
    assert reused.status_code == 201, reused.text
    assert await event_judges(event["id"]) == {JUDGE_1_ID}

    # Asignarlo a un comité también lo vincula al evento.
    committee = await _create_committee(client, event["id"])
    await client.put(
        f"{API}/committees/{committee['id']}/judges", headers=ADMIN, json=[{"judge_id": JUDGE_2_ID}]
    )
    assert await event_judges(event["id"]) == {JUDGE_1_ID, JUDGE_2_ID}

    # Una invitación pendiente solo aparece en su evento.
    other = await _create_event(client)
    email = f"evento-{uuid.uuid4().hex[:8]}@munych.dev"
    invited = await client.post(
        f"{API}/judges",
        headers=ADMIN,
        json={"email": email, "full_name": "Pendiente", "event_id": other["id"]},
    )
    assert fake_supabase.invited == [email]
    assert invited.json()["judge_id"] in await event_judges(other["id"], "judges/invitations")
    assert await event_judges(event["id"], "judges/invitations") == set()

    missing = await client.post(
        f"{API}/judges",
        headers=ADMIN,
        json={"email": email, "full_name": "X", "event_id": str(uuid.uuid4())},
    )
    assert missing.status_code == 404


async def test_judge_panel_reads(client: AsyncClient) -> None:
    committees = (await client.get(f"{API}/judge/committees", headers=JUDGE_1)).json()
    disec = next(c for c in committees if c["committee_id"] == DISEC_ID)
    assert disec["role"] == "chair"
    assert disec["event"]["timezone"] == "America/Santo_Domingo"

    detail = await client.get(f"{API}/judge/committees/{DISEC_ID}", headers=JUDGE_1)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert len(body["delegations"]) == 6
    assert len(body["rubric"]["criteria"]) == 6
    assert body["rubric"]["criteria"][0]["level_descriptors"]["1"] == "Inicial"
    assert [s["number"] for s in body["sessions"]] == [1, 2]

    event = await _create_event(client)
    committee = await _create_committee(client, event["id"])
    forbidden = await client.get(f"{API}/judge/committees/{committee['id']}", headers=JUDGE_1)
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "JUDGE_NOT_ASSIGNED"
