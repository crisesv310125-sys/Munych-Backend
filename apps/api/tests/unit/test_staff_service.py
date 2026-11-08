"""`StaffService` con un repositorio en memoria: rúbrica, evaluaciones y premios."""

import uuid
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import pytest

from munych_api.modules.identity.schemas import JudgeInvite, JudgeOut
from munych_api.modules.identity.service import IdentityService
from munych_api.modules.staff.repository import DELEGATE_KINDS, StaffRepository
from munych_api.modules.staff.schemas import (
    AccessLinkIn,
    AssignAwardIn,
    AwardIn,
    ConfirmAwardsIn,
    CriterionIn,
    MemberIn,
    PersonIn,
    RubricIn,
    StaffEvaluationIn,
    StaffInviteIn,
    StaffTypeIn,
)
from munych_api.modules.staff.service import StaffService
from munych_api.modules.voting.tokens import hash_token
from munych_api.shared.kernel import DomainError, ErrorCode

NOW = datetime(2026, 11, 12, 15, 0, tzinfo=UTC)
ORG = uuid.uuid4()
EVENT = uuid.uuid4()
NEXT_EVENT = uuid.uuid4()
CS, AG, NEXT_AG = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


class FixedClock:
    def now(self) -> datetime:
        return NOW


class FakeRepo:
    def __init__(self) -> None:
        # Dos eventos de la misma organización: el staff sirve para ambos.
        self.event_rows = [
            {
                "id": NEXT_EVENT,
                "name": "MUNYCH 2027",
                "status": "draft",
                "event_type": "mun_regular",
                "starts_on": date(2027, 3, 1),
                "ends_on": date(2027, 3, 3),
            },
            {
                "id": EVENT,
                "name": "SD-MUN 2026",
                "status": "active",
                "event_type": "mun_regular",
                "starts_on": date(2026, 11, 11),
                "ends_on": date(2026, 11, 14),
            },
        ]
        self.committees = [
            {"id": AG, "name": "Asamblea General", "acronym": "AG", "event_id": EVENT},
            {"id": CS, "name": "Consejo de Seguridad", "acronym": "CS", "event_id": EVENT},
            {"id": NEXT_AG, "name": "Asamblea 2027", "acronym": "AG27", "event_id": NEXT_EVENT},
        ]
        # Una delegación por comité, con un delegado cada una.
        self.delegations = [
            {"id": uuid.uuid4(), "committee_id": c["id"], "label": f"País {c['acronym']}{i}"}
            for c in self.committees
            for i in range(3)
        ]
        self.delegates = [
            {"id": uuid.uuid4(), "delegation_id": d["id"], "name": f"Delegado {d['label']}"}
            for d in self.delegations
        ]
        self.types: dict[UUID, dict[str, Any]] = {}
        self.people_rows: dict[UUID, dict[str, Any]] = {}
        self.member_rows: dict[UUID, dict[str, Any]] = {}
        self.evaluation_rows: list[dict[str, Any]] = []
        self.award_rows: dict[UUID, dict[str, Any]] = {}
        self.assignment_rows: list[dict[str, Any]] = []
        self.confirmation_rows: dict[tuple[UUID, UUID], datetime | None] = {}
        self.auth_users: dict[str, UUID] = {}
        self.committee_roles: dict[tuple[UUID, UUID], str] = {}

    # organización, eventos y comités
    async def organization_name(self, organization_id: UUID) -> str:
        return "MUNYCH Association"

    async def events(self, organization_id: UUID) -> list[dict[str, Any]]:
        return list(self.event_rows) if organization_id == ORG else []

    async def event_committees(self, event_id: UUID) -> list[dict[str, Any]]:
        return [
            {k: c[k] for k in ("id", "name", "acronym")}
            for c in self.committees
            if c["event_id"] == event_id
        ]

    async def organization_committee_ids(self, organization_id: UUID) -> set[UUID]:
        return {cast(UUID, c["id"]) for c in self.committees}

    async def candidates(
        self, event_id: UUID, evaluates: str, committee_ids: list[UUID] | None
    ) -> list[dict[str, Any]]:
        acronyms = {c["id"]: c["acronym"] for c in self.committees}
        in_event = {c["id"] for c in self.committees if c["event_id"] == event_id}
        out = []
        for d in self.delegations:
            if d["committee_id"] not in in_event:
                continue
            if committee_ids is not None and d["committee_id"] not in committee_ids:
                continue
            base = {
                "committee_id": d["committee_id"],
                "committee_acronym": acronyms[d["committee_id"]],
                "delegation_id": d["id"],
            }
            if evaluates in DELEGATE_KINDS:
                out += [
                    {**base, "candidate_id": p["id"], "label": p["name"], "sublabel": d["label"]}
                    for p in self.delegates
                    if p["delegation_id"] == d["id"]
                ]
            else:
                out.append({**base, "candidate_id": d["id"], "label": d["label"], "sublabel": None})
        return out

    # tipos
    async def list_types(self, event_id: UUID) -> list[dict[str, Any]]:
        return [t for t in self.types.values() if t["archived_at"] is None]

    async def get_type(self, type_id: UUID, organization_id: UUID) -> dict[str, Any] | None:
        t = self.types.get(type_id)
        return dict(t) if t and t["archived_at"] is None else None

    async def name_taken(self, event_id: UUID, name: str, exclude: UUID | None = None) -> bool:
        return any(
            t["name"].lower() == name.lower() and t["id"] != exclude
            for t in self.types.values()
            if t["archived_at"] is None
        )

    async def insert_type(self, values: dict[str, Any]) -> UUID:
        type_id = uuid.uuid4()
        self.types[type_id] = {
            "id": type_id,
            "scale_min": Decimal(0),
            "scale_max": Decimal(10),
            "scale_step": Decimal("0.5"),
            "position": len(self.types),
            "archived_at": None,
            **values,
        }
        return type_id

    async def update_type(self, type_id: UUID, values: dict[str, Any]) -> None:
        self.types[type_id].update(values)

    # premios
    async def awards(self, type_ids: list[UUID]) -> list[dict[str, Any]]:
        return [
            a
            for a in self.award_rows.values()
            if a["staff_type_id"] in type_ids and a["archived_at"] is None
        ]

    async def get_award(self, award_id: UUID, organization_id: UUID) -> dict[str, Any] | None:
        return self.award_rows.get(award_id)

    async def insert_awards(self, type_id: UUID, items: list[dict[str, Any]]) -> None:
        for i, item in enumerate(items):
            award_id = uuid.uuid4()
            self.award_rows[award_id] = {
                "id": award_id,
                "staff_type_id": type_id,
                "position": len(self.award_rows) + i,
                "archived_at": None,
                **item,
            }

    async def update_award(self, award_id: UUID, values: dict[str, Any]) -> None:
        self.award_rows[award_id].update(values)

    async def assignments(self, award_ids: list[UUID], event_id: UUID) -> list[dict[str, Any]]:
        return [
            a
            for a in self.assignment_rows
            if a["award_id"] in award_ids and a["event_id"] == event_id
        ]

    async def upsert_assignment(self, values: dict[str, Any]) -> None:
        key = ("award_id", "event_id", "committee_id", "position")
        for a in self.assignment_rows:
            if all(a[k] == values[k] for k in key):
                a.update(values)
                return
        self.assignment_rows.append(dict(values))

    async def confirmations(
        self, type_ids: list[UUID], event_id: UUID
    ) -> dict[UUID, datetime | None]:
        return {
            t: at
            for (t, e), at in self.confirmation_rows.items()
            if t in type_ids and e == event_id
        }

    async def set_confirmation(
        self, type_id: UUID, event_id: UUID, confirmed_at: datetime | None, by: UUID | None
    ) -> None:
        self.confirmation_rows[type_id, event_id] = confirmed_at

    # personas y miembros
    def _member_view(self, m: dict[str, Any]) -> dict[str, Any]:
        p = self.people_rows[m["person_id"]]
        return {
            **m,
            **{k: p[k] for k in ("full_name", "email", "title", "token_hash")},
            **{k: p[k] for k in ("token_issued_at", "token_expires_at", "last_used_at")},
        }

    async def members(self, type_ids: list[UUID]) -> list[dict[str, Any]]:
        return [
            self._member_view(m)
            for m in self.member_rows.values()
            if m["staff_type_id"] in type_ids
        ]

    async def get_member(self, member_id: UUID, organization_id: UUID) -> dict[str, Any] | None:
        return self.member_rows.get(member_id)

    async def people(self, organization_id: UUID) -> list[dict[str, Any]]:
        return [
            {
                **p,
                "types": [
                    self.types[m["staff_type_id"]]["name"]
                    for m in self.member_rows.values()
                    if m["person_id"] == p["id"] and m["removed_at"] is None
                ],
            }
            for p in self.people_rows.values()
        ]

    async def get_person(self, person_id: UUID, organization_id: UUID) -> dict[str, Any] | None:
        return self.people_rows.get(person_id)

    async def person_by_email(self, organization_id: UUID, email: str) -> dict[str, Any] | None:
        return next(
            (p for p in self.people_rows.values() if (p["email"] or "") == email.lower()), None
        )

    async def insert_person(self, values: dict[str, Any]) -> UUID:
        person_id = uuid.uuid4()
        self.people_rows[person_id] = {
            "id": person_id,
            "token_hash": None,
            "token_issued_at": None,
            "token_expires_at": None,
            "last_used_at": None,
            **values,
        }
        return person_id

    async def update_person(self, person_id: UUID, values: dict[str, Any]) -> None:
        self.people_rows[person_id].update(values)

    async def upsert_member(
        self,
        type_id: UUID,
        person_id: UUID,
        role: str,
        committee_ids: list[UUID],
        *,
        event_id: UUID | None,
        judge_id: UUID | None = None,
    ) -> UUID:
        for m in self.member_rows.values():
            if (m["staff_type_id"], m["person_id"], m["event_id"]) == (
                type_id,
                person_id,
                event_id,
            ):
                m.update(role=role, committee_ids=committee_ids, removed_at=None)
                return UUID(str(m["id"]))
        member_id = uuid.uuid4()
        self.member_rows[member_id] = {
            "id": member_id,
            "staff_type_id": type_id,
            "person_id": person_id,
            "event_id": event_id,
            "judge_id": judge_id,
            "role": role,
            "committee_ids": committee_ids,
            "removed_at": None,
            "evaluations_count": True,
        }
        return member_id

    async def update_member(self, member_id: UUID, values: dict[str, Any]) -> None:
        self.member_rows[member_id].update(values)

    async def organization_judges(self, organization_id: UUID) -> list[dict[str, Any]]:
        return [{"full_name": "Jueza Uno", "email": "jueza@example.org"}]

    async def user_id_by_email(self, email: str) -> UUID | None:
        return self.auth_users.get(email.lower())

    async def assign_committee_role(
        self, judge_id: UUID, committee_ids: list[UUID], role: str
    ) -> None:
        for c in committee_ids:
            self.committee_roles[c, judge_id] = role

    async def event_members(self, event_id: UUID, organization_id: UUID) -> list[dict[str, Any]]:
        out = []
        for m in self.member_rows.values():
            if m["removed_at"] is not None or m["event_id"] not in (None, event_id):
                continue
            t = self.types[m["staff_type_id"]]
            out.append(
                {
                    **self._member_view(m),
                    "type_name": t["name"],
                    "type_code": t["code"],
                    "type_color": t["color"],
                    "type_access": t.get("access", "link"),
                }
            )
        return out

    # enlace personal
    async def person_by_token_hash(self, token_hash: str) -> dict[str, Any] | None:
        p = next((p for p in self.people_rows.values() if p["token_hash"] == token_hash), None)
        if p is None:
            return None
        return {**p, "organization_name": "MUNYCH Association"}

    async def person_types(self, person_id: UUID) -> list[dict[str, Any]]:
        return [
            {
                **self.types[m["staff_type_id"]],
                "member_id": m["id"],
                "role": m["role"],
                "member_committee_ids": m["committee_ids"],
                "member_event_id": m["event_id"],
            }
            for m in self.member_rows.values()
            if m["person_id"] == person_id and m["removed_at"] is None
        ]

    # evaluaciones
    async def evaluations(self, member_ids: list[UUID]) -> list[dict[str, Any]]:
        return [e for e in self.evaluation_rows if e["member_id"] in member_ids]

    async def any_evaluation(self, type_id: UUID) -> bool:
        ids = {m["id"] for m in self.member_rows.values() if m["staff_type_id"] == type_id}
        return any(e["member_id"] in ids for e in self.evaluation_rows)

    async def upsert_evaluation(
        self,
        member_id: UUID,
        candidate_id: UUID,
        values: dict[str, Any],
        comment: str | None,
        client_updated_at: datetime | None,
    ) -> dict[str, Any]:
        for e in self.evaluation_rows:
            if (e["member_id"], e["candidate_id"]) == (member_id, candidate_id):
                e.update(values=values, comment=comment, updated_at=NOW)
                return e
        row = {
            "member_id": member_id,
            "candidate_id": candidate_id,
            "values": values,
            "comment": comment,
            "created_at": NOW,
            "updated_at": None,
        }
        self.evaluation_rows.append(row)
        return row


class FakeAuthAdmin:
    """Supabase Auth en memoria: registra los correos enviados y el metadata en ese momento."""

    def __init__(self, repo: FakeRepo) -> None:
        self.repo = repo
        self.metadata: dict[UUID, dict[str, str]] = {}
        self.sent: list[tuple[str, dict[str, str]]] = []

    async def create_confirmed_user(self, email: str, data: Mapping[str, str]) -> UUID:
        user_id = uuid.uuid4()
        self.repo.auth_users[email] = user_id
        self.metadata[user_id] = dict(data)
        return user_id

    async def update_user_metadata(self, user_id: UUID, data: Mapping[str, str]) -> None:
        self.metadata.setdefault(user_id, {}).update(data)

    async def send_magic_link(self, email: str) -> None:
        self.sent.append((email, dict(self.metadata[self.repo.auth_users[email]])))

    async def invite_user_by_email(
        self, email: str, *, redirect_to: str | None = None, data: Mapping[str, str] | None = None
    ) -> UUID:  # pragma: no cover — las invitaciones van por IdentityService
        raise AssertionError("no se usa")


class FakeIdentity:
    def __init__(self) -> None:
        self.invited: list[JudgeInvite] = []

    async def invite_judge(self, organization_id: UUID, data: JudgeInvite) -> JudgeOut:
        self.invited.append(data)
        return JudgeOut(
            judge_id=uuid.uuid4(), email=data.email, full_name=data.full_name, active=True
        )


def make() -> tuple[StaffService, FakeRepo]:
    repo = FakeRepo()
    return StaffService(cast(StaffRepository, repo), FixedClock()), repo


def make_with_auth() -> tuple[StaffService, FakeRepo, FakeAuthAdmin, FakeIdentity]:
    repo = FakeRepo()
    auth, identity = FakeAuthAdmin(repo), FakeIdentity()
    service = StaffService(
        cast(StaffRepository, repo),
        FixedClock(),
        identity=cast(IdentityService, identity),
        auth_admin=auth,
        panel_url="https://panel.test",
        api_url="https://api.test/api/v1",
    )
    return service, repo, auth, identity


async def _press_type(svc: StaffService, **kwargs: Any) -> UUID:
    body = StaffTypeIn(
        name="Prensa",
        evaluates="delegations",
        template="press",
        min_evaluators=1,
        awards=[AwardIn(name="Mejor periodista"), AwardIn(name="Mención de prensa", winners=2)],
        **kwargs,
    )
    return (await svc.create_type(ORG, body)).id


async def _member(svc: StaffService, type_id: UUID, name: str, **kwargs: Any) -> UUID:
    detail = await svc.add_member(ORG, type_id, MemberIn(person=PersonIn(full_name=name), **kwargs))
    return next(m.id for m in detail.members if m.full_name == name)


async def test_create_type_from_template() -> None:
    svc, _ = make()
    detail = await svc.detail(ORG, await _press_type(svc))
    assert detail.code == "PR"
    assert detail.rubric.valid
    assert len(detail.rubric.criteria) == 5
    assert detail.status == "not_configured"  # aún sin miembros
    assert [a.slots_total for a in detail.awards] == [1, 2]


async def test_rubric_must_sum_100_and_scale_is_locked_with_evaluations() -> None:
    svc, repo = make()
    type_id = await _press_type(svc)
    bad = RubricIn(
        criteria=[
            CriterionIn(name="A", weight=Decimal(50)),
            CriterionIn(name="B", weight=Decimal(35)),
        ]
    )
    with pytest.raises(DomainError) as exc:
        await svc.put_rubric(ORG, type_id, bad)
    assert exc.value.code == ErrorCode.WEIGHTS_MUST_SUM_100

    member_id = await _member(svc, type_id, "Valeria")
    repo.evaluation_rows.append(
        {"member_id": member_id, "candidate_id": repo.delegations[0]["id"], "values": {}}
    )
    rescaled = RubricIn(
        scale_max=Decimal(100),
        criteria=[
            CriterionIn(name="A", weight=Decimal(50)),
            CriterionIn(name="B", weight=Decimal(50)),
        ],
    )
    with pytest.raises(DomainError) as exc:
        await svc.put_rubric(ORG, type_id, rescaled)
    assert exc.value.code == ErrorCode.CONFLICT
    # Cambiar solo los pesos sí se puede (recalcula, no borra).
    same_scale = RubricIn(
        criteria=[
            CriterionIn(id="c1", name="A", weight=Decimal(50)),
            CriterionIn(name="B", weight=Decimal(50)),
        ]
    )
    detail = await svc.put_rubric(ORG, type_id, same_scale)
    assert next(c.id for c in detail.rubric.criteria) == "c1"


async def test_member_link_and_evaluation_flow() -> None:
    svc, repo = make()
    type_id = await _press_type(svc)
    member_id = await _member(svc, type_id, "Rodrigo", committee_ids=[CS])
    person_id = repo.member_rows[member_id]["person_id"]

    link = await svc.issue_link(
        ORG, person_id, AccessLinkIn(link_base="https://panel.test/#/staff/")
    )
    assert link.url.endswith(link.token)
    assert repo.people_rows[person_id]["token_hash"] == hash_token(link.token)
    person = await svc.authenticate(link.token)

    me = await svc.me(person)
    (assignment,) = me.assignments
    assert assignment.open
    assert {c.committee_acronym for c in assignment.candidates} == {"CS"}
    target = assignment.candidates[0].candidate_id
    criteria = [c.id for c in assignment.criteria]

    async def save(values: dict[str, str], candidate: UUID = target) -> Any:
        return await svc.save_evaluation(
            person,
            StaffEvaluationIn(
                member_id=member_id,
                event_id=EVENT,
                candidate_id=candidate,
                values={k: Decimal(v) for k, v in values.items()},
            ),
        )

    partial = await save({criteria[0]: "8.5"})
    assert not partial.complete
    done = await save(dict.fromkeys(criteria, "9"))
    assert done.complete

    for values, code in (
        ({criteria[0]: "11"}, ErrorCode.VALUE_OUT_OF_RANGE),
        ({criteria[0]: "8.25"}, ErrorCode.VALUE_OUT_OF_RANGE),
        ({"otro": "5"}, ErrorCode.VALIDATION_ERROR),
    ):
        with pytest.raises(DomainError) as exc:
            await save(values)
        assert exc.value.code == code

    ag_candidate = cast(UUID, next(d["id"] for d in repo.delegations if d["committee_id"] == AG))
    with pytest.raises(DomainError) as exc:
        await save({criteria[0]: "5"}, ag_candidate)
    assert exc.value.code == ErrorCode.FORBIDDEN

    detail = await svc.detail(ORG, type_id)
    (member,) = detail.members
    assert (member.access, member.evaluated, member.assigned) == ("active", 1, 3)
    assert detail.status == "in_progress"


async def test_invalid_link_is_rejected() -> None:
    svc, _ = make()
    with pytest.raises(DomainError) as exc:
        await svc.authenticate("x" * 32)
    assert exc.value.code == ErrorCode.UNAUTHORIZED


async def test_awards_suggest_assign_and_confirm() -> None:
    svc, repo = make()
    type_id = await _press_type(svc)
    member_id = await _member(svc, type_id, "Camila")
    criteria = [c["id"] for c in repo.types[type_id]["criteria"]]
    # Notas: delegación i recibe 10 - i en todos los criterios.
    for i, d in enumerate(repo.delegations):
        repo.evaluation_rows.append(
            {
                "member_id": member_id,
                "candidate_id": d["id"],
                "values": dict.fromkeys(criteria, 10 - i),
            }
        )
    ranking = await svc.ranking(ORG, type_id, None, None)
    best, mention = ranking.awards
    first, second, third = (r.candidate_id for r in ranking.rows[:3])
    assert best.slots[0].suggested_candidate_id == first
    assert [s.suggested_candidate_id for s in mention.slots] == [second, third]

    with pytest.raises(DomainError) as exc:
        await svc.confirm_awards(ORG, type_id, ConfirmAwardsIn(event_id=EVENT), uuid.uuid4())
    assert "Falta asignar 3 premios" in exc.value.detail

    admin = uuid.uuid4()
    await svc.assign_award(
        ORG, best.id, AssignAwardIn(event_id=EVENT, position=1, candidate_id=first), admin
    )
    # El admin elige a otro para la 1.ª mención: se guarda el sugerido y el motivo.
    other = ranking.rows[4].candidate_id
    after = await svc.assign_award(
        ORG,
        mention.id,
        AssignAwardIn(
            event_id=EVENT, position=1, candidate_id=other, override_reason="Mejor cobertura"
        ),
        admin,
    )
    row = next(a for a in repo.assignment_rows if a["candidate_id"] == other)
    assert row["suggested_candidate_id"] == second
    assert row["assigned_by"] == admin
    # La 2.ª mención ahora sugiere al 2.º lugar (el 1.º ya tiene premio).
    assert after.awards[1].slots[1].suggested_candidate_id == second

    await svc.assign_award(
        ORG, mention.id, AssignAwardIn(event_id=EVENT, position=2, candidate_id=second), admin
    )
    detail = await svc.confirm_awards(ORG, type_id, ConfirmAwardsIn(event_id=EVENT), admin)
    assert detail.awards_confirmed_at == NOW
    with pytest.raises(DomainError):
        await svc.assign_award(
            ORG, best.id, AssignAwardIn(event_id=EVENT, position=1, candidate_id=None), admin
        )


async def test_removed_member_keeps_evaluations() -> None:
    svc, repo = make()
    type_id = await _press_type(svc)
    member_id = await _member(svc, type_id, "Mateo")
    criteria = [c["id"] for c in repo.types[type_id]["criteria"]]
    target = repo.delegations[0]["id"]
    repo.evaluation_rows.append(
        {"member_id": member_id, "candidate_id": target, "values": dict.fromkeys(criteria, 8)}
    )
    detail = await svc.remove_member(ORG, member_id)
    assert detail.members[0].removed_at == NOW
    assert detail.members_count == 0
    ranking = await svc.ranking(ORG, type_id, None, None)
    assert ranking.rows[0].candidate_id == target
    assert ranking.rows[0].score == 80.0


async def test_people_includes_event_judges() -> None:
    svc, _ = make()
    type_id = await _press_type(svc)
    await _member(svc, type_id, "Lucía")
    people = await svc.people(ORG)
    assert [(p.full_name, p.source, p.types) for p in people] == [
        ("Lucía", "staff", ["Prensa"]),
        ("Jueza Uno", "judge", []),
    ]


async def test_staff_is_shared_across_events() -> None:
    """El tipo es de la organización: cada evento tiene sus candidatos y sus premios."""
    svc, _ = make()
    type_id = await _press_type(svc)
    await _member(svc, type_id, "Valeria")
    overview = await svc.overview(ORG, None)
    assert overview.event_id == EVENT  # por defecto, el evento activo
    assert [e.id for e in overview.events] == [NEXT_EVENT, EVENT]
    now_detail = await svc.detail(ORG, type_id, EVENT)
    next_detail = await svc.detail(ORG, type_id, NEXT_EVENT)
    assert now_detail.candidates == 6
    assert next_detail.candidates == 3
    assert {c.acronym for c in next_detail.committees} == {"AG27"}
    # Premio asignado en un evento: el otro sigue sin asignar.
    ranking = await svc.ranking(ORG, type_id, EVENT, None)
    best = ranking.awards[0]
    await svc.assign_award(
        ORG,
        best.id,
        AssignAwardIn(event_id=EVENT, position=1, candidate_id=ranking.rows[0].candidate_id),
        uuid.uuid4(),
    )
    assert (await svc.detail(ORG, type_id, EVENT)).awards[0].slots_assigned == 1
    assert (await svc.detail(ORG, type_id, NEXT_EVENT)).awards[0].slots_assigned == 0


# ---------------------------------------------------------------- invitar con rol (por evento)


async def test_invite_link_staff_sends_qr_email_and_clears_the_link() -> None:
    svc, repo, auth, identity = make_with_auth()
    type_id = await _press_type(svc)
    out = await svc.invite(
        ORG,
        EVENT,
        StaffInviteIn(
            full_name="Valeria Gómez",
            email="Valeria@Example.org",
            role="staff",
            staff_type_id=type_id,
            committee_ids=[CS],
        ),
    )
    assert out.kind == "link"
    assert out.url is not None
    assert out.url.startswith("https://panel.test/#/staff/evaluar/")
    assert identity.invited == []  # sin cuenta con contraseña
    ((email, data),) = auth.sent
    assert email == "valeria@example.org"
    assert data["staff_qr_url"].startswith("https://api.test/api/v1/staff/qr/")
    assert data["staff_type"] == "Prensa"
    # Tras enviar, el enlace no se queda en Supabase Auth.
    user_id = repo.auth_users["valeria@example.org"]
    assert auth.metadata[user_id]["staff_url"] == ""
    # Miembro del tipo en este evento, con su comité.
    (member,) = repo.member_rows.values()
    assert (member["event_id"], member["committee_ids"]) == (EVENT, [CS])
    # El QR del correo se puede pedir con el token vigente.
    token = out.url.rsplit("/", 1)[1]
    assert (await svc.qr_png(token)).startswith(b"\x89PNG")
    (listed,) = await svc.event_members(ORG, EVENT)
    assert listed.access == "invited"
    assert await svc.event_members(ORG, NEXT_EVENT) == []


async def test_invite_account_staff_gets_password_and_chair_role() -> None:
    svc, repo, auth, identity = make_with_auth()
    mesa = (
        await svc.create_type(
            ORG, StaffTypeIn(name="Mesa Directiva", access="account", counts_as="chair")
        )
    ).id
    with pytest.raises(DomainError):  # la mesa necesita su comité
        await svc.invite(
            ORG,
            EVENT,
            StaffInviteIn(full_name="Ana", email="ana@x.org", role="staff", staff_type_id=mesa),
        )
    out = await svc.invite(
        ORG,
        EVENT,
        StaffInviteIn(
            full_name="Ana", email="ana@x.org", role="staff", staff_type_id=mesa, committee_ids=[AG]
        ),
    )
    assert out.kind == "account"
    assert [i.email for i in identity.invited] == ["ana@x.org"]
    assert auth.sent == []  # sin QR: entra con contraseña
    assert list(repo.committee_roles.values()) == ["chair"]


async def test_judge_role_only_in_events_with_judges() -> None:
    svc, repo, _, identity = make_with_auth()
    body = StaffInviteIn(full_name="Juan", email="juan@x.org", role="judge", committee_ids=[AG])
    with pytest.raises(DomainError) as exc:  # MUN regular: no hay jueces
        await svc.invite(ORG, EVENT, body)
    assert exc.value.code == ErrorCode.CONFLICT
    repo.event_rows[1]["event_type"] = "national_championship"
    out = await svc.invite(ORG, EVENT, body)
    assert out.kind == "judge"
    assert list(repo.committee_roles.values()) == ["judge"]
    assert identity.invited[0].event_id == EVENT
