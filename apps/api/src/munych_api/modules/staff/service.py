"""Gestión de staff (handoff «Gestión de staff», 2026-11-08).

El staff es de la **organización**: tipos de staff, personas, miembros, rúbricas y
premios se definen una vez y sirven para todos sus eventos. Lo que depende de un evento
(candidatos, avance, ranking, asignación y confirmación de premios) se calcula en un
**evento de contexto**: el que pide el panel o, si no pide ninguno, el evento activo más
reciente de la organización.

Admin: tipos de staff, miembros, rúbrica propia, ranking y premios propios.
Miembro del staff: entra con su enlace personal y evalúa a los candidatos de sus
asignaciones en los eventos no cerrados (`me` y `save_evaluation`).

Nada se borra: quitar un tipo, un premio o un miembro los marca (`archived_at`,
`removed_at`) y las evaluaciones se conservan.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from munych_api.modules.staff.repository import StaffRepository
from munych_api.modules.staff.schemas import (
    AccessLinkIn,
    AccessLinkOut,
    AccessStatus,
    AssignAwardIn,
    AwardIn,
    AwardOut,
    AwardPatch,
    AwardSlotOut,
    CommitteeRefOut,
    ConfirmAwardsIn,
    CriterionOut,
    EventRefOut,
    MemberIn,
    MemberOut,
    MemberPatch,
    PersonOut,
    PersonPatch,
    RankingOut,
    RankingRowOut,
    RubricIn,
    RubricOut,
    StaffAssignmentOut,
    StaffCandidateOut,
    StaffEvaluationIn,
    StaffEvaluationOut,
    StaffMeOut,
    StaffOverviewOut,
    StaffTypeDetailOut,
    StaffTypeIn,
    StaffTypePatch,
    StaffTypeStatus,
    StaffTypeSummaryOut,
)
from munych_api.modules.staff.templates import PALETTE, initials, template_criteria
from munych_api.modules.voting.tokens import expires_at, hash_token, looks_like_token, new_token
from munych_api.scoring_engine.staff import (
    CandidateResult,
    StaffEvaluation,
    StaffRubric,
    candidate_results,
    evaluation_score,
    rubric_from_json,
    values_from_json,
)
from munych_api.shared.kernel import Clock, DomainError, ErrorCode, NotFoundError
from munych_api.shared.kernel.catalog import EVENT_TYPES

INVALID_LINK = "Tu enlace no es válido o ya venció. Pide uno nuevo a la coordinación del evento"
TOUCH_INTERVAL = timedelta(minutes=5)
LINK_DAYS_WITHOUT_EVENTS = timedelta(days=30)
"""Vigencia del enlace si la organización no tiene eventos abiertos."""


@dataclass(frozen=True, slots=True)
class StaffPerson:
    """Persona del staff autenticada con su enlace."""

    id: UUID
    organization_id: UUID
    full_name: str
    title: str | None
    organization_name: str


def _f(value: Decimal | None) -> float | None:
    return None if value is None else round(float(value), 2)


def access_status(person: dict[str, Any], now: datetime) -> AccessStatus:
    if person.get("token_issued_at") is None:
        return "not_invited"
    expires = person.get("token_expires_at")
    if expires is not None and expires <= now:
        return "expired"
    return "active" if person.get("last_used_at") is not None else "invited"


def _rubric(row: dict[str, Any]) -> StaffRubric:
    return rubric_from_json(row["scale_min"], row["scale_max"], row["criteria"] or [])


def _scope(row: dict[str, Any], committees: list[dict[str, Any]]) -> list[UUID] | None:
    """Comités del alcance del tipo en el evento (`None` = todos los del evento)."""
    if row["all_committees"]:
        return None
    wanted = set(row["committee_ids"] or [])
    return [c["id"] for c in committees if c["id"] in wanted]


def _member_candidates(
    member: dict[str, Any], candidates: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Candidatos que le tocan al miembro: los de sus comités (ninguno = todos los del tipo).

    Las filas de `person_types` traen los comités del miembro en `member_committee_ids`
    (`committee_ids` ahí es el alcance del tipo).
    """
    key = "member_committee_ids" if "member_committee_ids" in member else "committee_ids"
    wanted = set(member.get(key) or [])
    if not wanted:
        return candidates
    return [c for c in candidates if c["committee_id"] in wanted]


def _counts(member: dict[str, Any]) -> bool:
    return member["removed_at"] is None or bool(member["evaluations_count"])


def default_event(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Evento de contexto por defecto: el activo más reciente; si no, el más reciente."""
    active = [e for e in events if e["status"] == "active"]
    candidates = active or events
    return candidates[0] if candidates else None


@dataclass(slots=True)
class _TypeContext:
    """Todo lo de un tipo de staff en el evento de contexto: avance, ranking y premios."""

    row: dict[str, Any]
    rubric: StaffRubric
    candidates: list[dict[str, Any]]
    members: list[dict[str, Any]]
    evaluations: list[dict[str, Any]]
    awards: list[dict[str, Any]]
    assignments: list[dict[str, Any]]
    committees: list[dict[str, Any]]
    confirmed_at: datetime | None = None
    _results: dict[UUID | None, list[CandidateResult]] = field(default_factory=dict)

    @property
    def configured(self) -> bool:
        return self.row["evaluates"] is not None

    @property
    def active_members(self) -> list[dict[str, Any]]:
        return [m for m in self.members if m["removed_at"] is None]

    @property
    def candidate_by_id(self) -> dict[UUID, dict[str, Any]]:
        return {c["candidate_id"]: c for c in self.candidates}

    def scope_committees(self) -> list[dict[str, Any]]:
        scope = _scope(self.row, self.committees)
        if scope is None:
            return self.committees
        wanted = set(scope)
        return [c for c in self.committees if c["id"] in wanted]

    def progress(self) -> tuple[int, int]:
        """(evaluaciones completas, evaluaciones esperadas) de los miembros activos."""
        done = expected = 0
        by_member: dict[UUID, set[UUID]] = defaultdict(set)
        for ev in self.evaluations:
            if evaluation_score(self.rubric, values_from_json(ev["values"])) is not None:
                by_member[ev["member_id"]].add(ev["candidate_id"])
        for m in self.active_members:
            mine = {c["candidate_id"] for c in _member_candidates(m, self.candidates)}
            expected += len(mine)
            done += len(mine & by_member[m["id"]])
        return done, expected

    def ranked(
        self, committee_id: UUID | None = None, tiebreak: str | None = None
    ) -> list[CandidateResult]:
        """Ranking de los candidatos (del comité, si se da) con el desempate indicado."""
        key = committee_id if tiebreak is None else None
        if tiebreak is None and key in self._results:
            return self._results[key]
        counted = {m["id"] for m in self.members if _counts(m)}
        ids = [
            str(c["candidate_id"])
            for c in self.candidates
            if committee_id is None or c["committee_id"] == committee_id
        ]
        result = candidate_results(
            self.rubric,
            (
                StaffEvaluation(
                    str(ev["member_id"]), str(ev["candidate_id"]), values_from_json(ev["values"])
                )
                for ev in self.evaluations
                if ev["member_id"] in counted
            ),
            ids,
            int(self.row["min_evaluators"]),
            tiebreak,
        )
        if tiebreak is None:
            self._results[committee_id] = result
        return result

    def slots(self, award: dict[str, Any]) -> list[tuple[UUID | None, int]]:
        positions = range(1, int(award["winners"]) + 1)
        if award["scope"] == "per_committee":
            return [(c["id"], p) for c in self.scope_committees() for p in positions]
        return [(None, p) for p in positions]

    def award_outs(self, with_slots: bool) -> list[AwardOut]:
        assigned = {(a["award_id"], a["committee_id"], a["position"]): a for a in self.assignments}
        used = {a["candidate_id"] for a in self.assignments if a["candidate_id"] is not None}
        suggested: set[UUID] = set()
        candidates = self.candidate_by_id
        acronyms = {c["id"]: c["acronym"] for c in self.committees}
        scores = {UUID(r.candidate_id): r.score for r in self.ranked()}
        out: list[AwardOut] = []
        for award in self.awards:
            slots: list[AwardSlotOut] = []
            done = 0
            ranking_cache: dict[UUID | None, list[CandidateResult]] = {}
            for committee_id, position in self.slots(award):
                row = assigned.get((award["id"], committee_id, position))
                candidate_id = row["candidate_id"] if row else None
                if candidate_id is not None:
                    done += 1
                if committee_id not in ranking_cache:
                    ranking_cache[committee_id] = self.ranked(
                        committee_id, award["tiebreak_criterion_id"]
                    )
                suggestion = next(
                    (
                        UUID(r.candidate_id)
                        for r in ranking_cache[committee_id]
                        if r.eligible
                        and UUID(r.candidate_id) not in used
                        and UUID(r.candidate_id) not in suggested
                    ),
                    None,
                )
                if candidate_id is None and suggestion is not None:
                    suggested.add(suggestion)
                if with_slots:
                    cand = candidates.get(candidate_id) if candidate_id else None
                    sugg = candidates.get(suggestion) if suggestion and not candidate_id else None
                    slots.append(
                        AwardSlotOut(
                            committee_id=committee_id,
                            committee_acronym=acronyms.get(committee_id) if committee_id else None,
                            position=position,
                            candidate_id=candidate_id,
                            candidate_label=cand["label"] if cand else None,
                            candidate_score=_f(scores.get(candidate_id)) if candidate_id else None,
                            suggested_candidate_id=suggestion if candidate_id is None else None,
                            suggested_label=sugg["label"] if sugg else None,
                            suggested_score=_f(scores.get(suggestion))
                            if sugg and suggestion
                            else None,
                            override_reason=row["override_reason"] if row else None,
                            assigned_at=row["assigned_at"] if row else None,
                        )
                    )
            out.append(
                AwardOut(
                    id=award["id"],
                    name=award["name"],
                    winners=award["winners"],
                    scope=award["scope"],
                    tiebreak_criterion_id=award["tiebreak_criterion_id"],
                    slots_total=len(self.slots(award)),
                    slots_assigned=done,
                    slots=slots,
                )
            )
        return out

    def status(self) -> StaffTypeStatus:
        if not self.configured or not self.active_members:
            return "not_configured"
        if not self.rubric.valid:
            return "invalid_rubric"
        done, expected = self.progress()
        if done == 0:
            return "not_started"
        return "complete" if expected and done >= expected else "in_progress"


def _criteria_out(row: dict[str, Any]) -> list[CriterionOut]:
    return [
        CriterionOut(
            id=str(c["id"]),
            name=str(c["name"]),
            description=c.get("description"),
            weight=float(c.get("weight", 0)),
        )
        for c in row["criteria"] or []
    ]


def _rubric_out(ctx: _TypeContext) -> RubricOut:
    return RubricOut(
        scale_min=float(ctx.row["scale_min"]),
        scale_max=float(ctx.row["scale_max"]),
        scale_step=float(ctx.row["scale_step"]),
        criteria=_criteria_out(ctx.row),
        weight_sum=float(ctx.rubric.weight_sum),
        valid=ctx.rubric.valid,
    )


def _closed_reason(row: dict[str, Any], confirmed_at: datetime | None) -> str | None:
    """Por qué un miembro no puede evaluar ahora en un evento abierto (None = puede)."""
    if row["evaluates"] is None:
        return "Este staff todavía no está configurado."
    if not _rubric(row).valid:
        return "La rúbrica de este staff todavía no está lista."
    if confirmed_at is not None:
        return "Los premios de este staff ya se confirmaron en este evento."
    return None


class StaffService:
    def __init__(self, repository: StaffRepository, clock: Clock) -> None:
        self._repo = repository
        self._clock = clock

    # ------------------------------------------------------------ carga

    async def _event_context(
        self, organization_id: UUID, event_id: UUID | None
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """(eventos de la organización, evento de contexto)."""
        events = await self._repo.events(organization_id)
        if event_id is None:
            return events, default_event(events)
        event = next((e for e in events if e["id"] == event_id), None)
        if event is None:
            raise NotFoundError("Evento no encontrado")
        return events, event

    async def _require_type(self, organization_id: UUID, type_id: UUID) -> dict[str, Any]:
        row = await self._repo.get_type(type_id, organization_id)
        if row is None:
            raise NotFoundError("Tipo de staff no encontrado")
        return row

    async def _contexts(
        self, rows: list[dict[str, Any]], event: dict[str, Any] | None
    ) -> tuple[list[_TypeContext], list[dict[str, Any]]]:
        committees = await self._repo.event_committees(event["id"]) if event else []
        ids = [r["id"] for r in rows]
        members = await self._repo.members(ids)
        awards = await self._repo.awards(ids)
        assignments = (
            await self._repo.assignments([a["id"] for a in awards], event["id"]) if event else []
        )
        confirmations = await self._repo.confirmations(ids, event["id"]) if event else {}
        evaluations = await self._repo.evaluations([m["id"] for m in members])
        out: list[_TypeContext] = []
        for row in rows:
            type_members = [m for m in members if m["staff_type_id"] == row["id"]]
            member_ids = {m["id"] for m in type_members}
            type_awards = [a for a in awards if a["staff_type_id"] == row["id"]]
            award_ids = {a["id"] for a in type_awards}
            candidates = (
                await self._repo.candidates(event["id"], row["evaluates"], _scope(row, committees))
                if event and row["evaluates"]
                else []
            )
            candidate_ids = {c["candidate_id"] for c in candidates}
            out.append(
                _TypeContext(
                    row=row,
                    rubric=_rubric(row),
                    candidates=candidates,
                    members=type_members,
                    # Solo las evaluaciones de candidatos de este evento.
                    evaluations=[
                        e
                        for e in evaluations
                        if e["member_id"] in member_ids and e["candidate_id"] in candidate_ids
                    ],
                    awards=type_awards,
                    assignments=[a for a in assignments if a["award_id"] in award_ids],
                    committees=committees,
                    confirmed_at=confirmations.get(row["id"]),
                )
            )
        return out, committees

    def _summary(self, ctx: _TypeContext) -> dict[str, Any]:
        done, expected = ctx.progress()
        active = ctx.active_members
        return {
            "id": ctx.row["id"],
            "name": ctx.row["name"],
            "code": ctx.row["code"],
            "color": ctx.row["color"],
            "description": ctx.row["description"],
            "evaluates": ctx.row["evaluates"],
            "all_committees": ctx.row["all_committees"],
            "committee_ids": list(ctx.row["committee_ids"] or []),
            "min_evaluators": ctx.row["min_evaluators"],
            "counts_as": ctx.row["counts_as"],
            "criteria_count": len(ctx.rubric.criteria),
            "weight_sum": float(ctx.rubric.weight_sum),
            "rubric_valid": ctx.rubric.valid,
            "awards": ctx.award_outs(with_slots=False),
            "members_count": len(active),
            "members_preview": [m["full_name"] for m in active[:4]],
            "candidates": len(ctx.candidates),
            "evaluations_done": done,
            "evaluations_expected": expected,
            "progress": round(done * 100 / expected, 1) if expected else None,
            "status": ctx.status(),
            "awards_confirmed_at": ctx.confirmed_at,
        }

    # ------------------------------------------------------------ lista de tipos

    async def overview(self, organization_id: UUID, event_id: UUID | None) -> StaffOverviewOut:
        events, event = await self._event_context(organization_id, event_id)
        contexts, _ = await self._contexts(await self._repo.list_types(organization_id), event)
        summaries = [StaffTypeSummaryOut(**self._summary(c)) for c in contexts]
        now = self._clock.now()
        people: dict[UUID, dict[str, Any]] = {}
        for ctx in contexts:
            for m in ctx.active_members:
                people[m["person_id"]] = m
        configured = [s for s in summaries if s.status != "not_configured"]
        done = sum(s.evaluations_done for s in configured)
        expected = sum(s.evaluations_expected for s in configured)
        weights = EVENT_TYPES[event["event_type"]].voter_weights if event else {}
        return StaffOverviewOut(
            organization_name=await self._repo.organization_name(organization_id),
            events=[EventRefOut(**{k: e[k] for k in EventRefOut.model_fields}) for e in events],
            event_id=event["id"] if event else None,
            event_name=event["name"] if event else None,
            event_type=event["event_type"] if event else None,
            staff_weight=_f(weights.get("staff")),
            chair_weight=_f(weights.get("chair")),
            types=summaries,
            people=len(people),
            people_active=sum(1 for p in people.values() if access_status(p, now) == "active"),
            awards_total=sum(a.slots_total for s in summaries for a in s.awards),
            awards_assigned=sum(a.slots_assigned for s in summaries for a in s.awards),
            progress=round(done * 100 / expected, 1) if expected else None,
        )

    async def detail(
        self, organization_id: UUID, type_id: UUID, event_id: UUID | None = None
    ) -> StaffTypeDetailOut:
        row = await self._require_type(organization_id, type_id)
        return await self._detail(organization_id, row, event_id)

    async def _detail(
        self, organization_id: UUID, row: dict[str, Any], event_id: UUID | None
    ) -> StaffTypeDetailOut:
        _, event = await self._event_context(organization_id, event_id)
        (ctx,), committees = await self._contexts([row], event)
        now = self._clock.now()
        other_types: dict[UUID, list[str]] = {
            p["id"]: [t for t in (p["types"] or []) if t != row["name"]]
            for p in await self._repo.people(organization_id)
        }
        complete: dict[UUID, set[UUID]] = defaultdict(set)
        for ev in ctx.evaluations:
            if evaluation_score(ctx.rubric, values_from_json(ev["values"])) is not None:
                complete[ev["member_id"]].add(ev["candidate_id"])
        members = []
        for m in ctx.members:
            mine = {c["candidate_id"] for c in _member_candidates(m, ctx.candidates)}
            members.append(
                MemberOut(
                    id=m["id"],
                    person_id=m["person_id"],
                    full_name=m["full_name"],
                    email=m["email"],
                    title=m["title"],
                    role=m["role"],
                    committee_ids=list(m["committee_ids"] or []),
                    access=access_status(m, now),
                    evaluated=len(mine & complete[m["id"]]),
                    assigned=len(mine),
                    removed_at=m["removed_at"],
                    evaluations_count=m["evaluations_count"],
                    other_types=other_types.get(m["person_id"], []),
                )
            )
        summary = self._summary(ctx)
        summary["awards"] = ctx.award_outs(with_slots=True)
        return StaffTypeDetailOut(
            **summary,
            event_id=event["id"] if event else None,
            rubric=_rubric_out(ctx),
            members=members,
            committees=[CommitteeRefOut(**c) for c in committees],
            evaluations_exist=await self._repo.any_evaluation(row["id"]),
        )

    # ------------------------------------------------------------ crear y editar tipos

    async def _check_committees(
        self, organization_id: UUID, committee_ids: list[UUID]
    ) -> list[UUID]:
        if not committee_ids:
            return []
        known = await self._repo.organization_committee_ids(organization_id)
        wanted = list(dict.fromkeys(committee_ids))
        if not set(wanted) <= known:
            raise NotFoundError("Algún comité no pertenece a la organización")
        return wanted

    async def create_type(
        self, organization_id: UUID, body: StaffTypeIn, event_id: UUID | None = None
    ) -> StaffTypeDetailOut:
        name = body.name.strip()
        if await self._repo.name_taken(organization_id, name):
            raise DomainError(ErrorCode.CONFLICT, f"Ya existe un tipo de staff llamado «{name}»")
        committee_ids = await self._check_committees(organization_id, body.committee_ids)
        if not body.all_committees and not committee_ids:
            raise DomainError(ErrorCode.VALIDATION_ERROR, "Elige al menos un comité")
        existing = await self._repo.list_types(organization_id)
        type_id = await self._repo.insert_type(
            {
                "organization_id": organization_id,
                "name": name,
                "code": (body.code or initials(name)).upper(),
                "color": body.color or PALETTE[len(existing) % (len(PALETTE) - 1)],
                "description": body.description,
                "evaluates": body.evaluates,
                "all_committees": body.all_committees,
                "committee_ids": [] if body.all_committees else committee_ids,
                "min_evaluators": body.min_evaluators,
                "counts_as": body.counts_as,
                "criteria": template_criteria(body.template),
            }
        )
        await self._repo.insert_awards(
            type_id,
            [
                {
                    "name": a.name.strip(),
                    "winners": a.winners,
                    "scope": a.scope,
                    "tiebreak_criterion_id": a.tiebreak_criterion_id,
                }
                for a in body.awards
            ],
        )
        return await self.detail(organization_id, type_id, event_id)

    async def update_type(
        self,
        organization_id: UUID,
        type_id: UUID,
        body: StaffTypePatch,
        event_id: UUID | None = None,
    ) -> StaffTypeDetailOut:
        row = await self._require_type(organization_id, type_id)
        data = body.model_dump(exclude_unset=True)
        values: dict[str, Any] = {}
        if data.get("archived"):
            await self._repo.update_type(type_id, {"archived_at": self._clock.now()})
            return await self._detail(organization_id, row, event_id)
        if data.get("name") is not None:
            name = data["name"].strip()
            if await self._repo.name_taken(organization_id, name, exclude=type_id):
                raise DomainError(
                    ErrorCode.CONFLICT, f"Ya existe un tipo de staff llamado «{name}»"
                )
            values["name"] = name
        if data.get("code") is not None:
            values["code"] = data["code"].upper()
        for key in ("color", "min_evaluators", "counts_as", "all_committees"):
            if data.get(key) is not None:
                values[key] = data[key]
        if "description" in data:
            values["description"] = (data["description"] or "").strip() or None
        if data.get("evaluates") is not None and data["evaluates"] != row["evaluates"]:
            if row["evaluates"] is not None and await self._repo.any_evaluation(type_id):
                raise DomainError(
                    ErrorCode.CONFLICT,
                    "No se puede cambiar a quién evalúa: ya hay evaluaciones capturadas",
                )
            values["evaluates"] = data["evaluates"]
        if data.get("committee_ids") is not None:
            values["committee_ids"] = await self._check_committees(
                organization_id, data["committee_ids"]
            )
        all_committees = values.get("all_committees", row["all_committees"])
        if all_committees:
            values["committee_ids"] = []
        elif not values.get("committee_ids", row["committee_ids"]):
            raise DomainError(ErrorCode.VALIDATION_ERROR, "Elige al menos un comité")
        await self._repo.update_type(type_id, values)
        return await self.detail(organization_id, type_id, event_id)

    async def put_rubric(
        self,
        organization_id: UUID,
        type_id: UUID,
        body: RubricIn,
        event_id: UUID | None = None,
    ) -> StaffTypeDetailOut:
        row = await self._require_type(organization_id, type_id)
        if body.scale_max <= body.scale_min:
            raise DomainError(ErrorCode.VALIDATION_ERROR, "La escala debe ir de menor a mayor")
        total = sum((c.weight for c in body.criteria), Decimal(0))
        if total != 100:
            raise DomainError(
                ErrorCode.WEIGHTS_MUST_SUM_100,
                f"Los pesos suman {total.normalize():f} %; deben sumar 100 %",
            )
        scale_changed = (
            Decimal(row["scale_min"]) != body.scale_min
            or Decimal(row["scale_max"]) != body.scale_max
            or Decimal(row["scale_step"]) != body.scale_step
        )
        if scale_changed and await self._repo.any_evaluation(type_id):
            raise DomainError(
                ErrorCode.CONFLICT,
                "No se puede cambiar la escala: ya hay evaluaciones con la escala actual",
            )
        known = {str(c["id"]) for c in row["criteria"] or []}
        criteria: list[dict[str, Any]] = []
        seen: set[str] = set()
        for c in body.criteria:
            cid = c.id if c.id in known and c.id not in seen else f"c{uuid4().hex[:8]}"
            seen.add(cid)
            criteria.append(
                {
                    "id": cid,
                    "name": c.name.strip(),
                    "description": (c.description or "").strip() or None,
                    "weight": float(c.weight),
                }
            )
        await self._repo.update_type(
            type_id,
            {
                "scale_min": body.scale_min,
                "scale_max": body.scale_max,
                "scale_step": body.scale_step,
                "criteria": criteria,
            },
        )
        return await self.detail(organization_id, type_id, event_id)

    # ------------------------------------------------------------ premios

    async def add_award(
        self,
        organization_id: UUID,
        type_id: UUID,
        body: AwardIn,
        event_id: UUID | None = None,
    ) -> StaffTypeDetailOut:
        await self._require_type(organization_id, type_id)
        await self._repo.insert_awards(
            type_id,
            [
                {
                    "name": body.name.strip(),
                    "winners": body.winners,
                    "scope": body.scope,
                    "tiebreak_criterion_id": body.tiebreak_criterion_id,
                }
            ],
        )
        return await self.detail(organization_id, type_id, event_id)

    async def update_award(
        self,
        organization_id: UUID,
        award_id: UUID,
        body: AwardPatch,
        event_id: UUID | None = None,
    ) -> StaffTypeDetailOut:
        award = await self._repo.get_award(award_id, organization_id)
        if award is None:
            raise NotFoundError("Premio no encontrado")
        row = await self._require_type(organization_id, award["staff_type_id"])
        data = body.model_dump(exclude_unset=True)
        values: dict[str, Any] = {}
        if data.get("archived"):
            values["archived_at"] = self._clock.now()
        for key in ("winners", "scope"):
            if data.get(key) is not None:
                values[key] = data[key]
        if data.get("name") is not None:
            values["name"] = data["name"].strip()
        if "tiebreak_criterion_id" in data:
            values["tiebreak_criterion_id"] = data["tiebreak_criterion_id"]
        await self._repo.update_award(award_id, values)
        return await self.detail(organization_id, row["id"], event_id)

    async def _confirmed_at(self, type_id: UUID, event_id: UUID) -> datetime | None:
        return (await self._repo.confirmations([type_id], event_id)).get(type_id)

    async def ranking(
        self,
        organization_id: UUID,
        type_id: UUID,
        event_id: UUID | None,
        committee_id: UUID | None,
    ) -> RankingOut:
        row = await self._require_type(organization_id, type_id)
        _, event = await self._event_context(organization_id, event_id)
        (ctx,), committees = await self._contexts([row], event)
        if committee_id is not None and committee_id not in {c["id"] for c in committees}:
            raise NotFoundError("Comité no encontrado en este evento")
        candidates = ctx.candidate_by_id
        awards = ctx.award_outs(with_slots=True)
        names = {a.id: a.name for a in awards}
        won: dict[UUID, list[str]] = defaultdict(list)
        for a in ctx.assignments:
            if a["candidate_id"] is not None and a["award_id"] in names:
                won[a["candidate_id"]].append(names[a["award_id"]])
        rows = []
        for r in ctx.ranked(committee_id):
            c = candidates[UUID(r.candidate_id)]
            rows.append(
                RankingRowOut(
                    candidate_id=c["candidate_id"],
                    label=c["label"],
                    sublabel=c["sublabel"],
                    committee_id=c["committee_id"],
                    committee_acronym=c["committee_acronym"],
                    score=_f(r.score),
                    evaluations=r.evaluations,
                    eligible=r.eligible,
                    position=r.position,
                    tied=r.tied,
                    awards=won.get(c["candidate_id"], []),
                )
            )
        return RankingOut(
            staff_type_id=type_id,
            event_id=event["id"] if event else None,
            committee_id=committee_id,
            min_evaluators=row["min_evaluators"],
            rows=rows,
            awards=awards,
            awards_confirmed_at=ctx.confirmed_at,
        )

    async def assign_award(
        self, organization_id: UUID, award_id: UUID, body: AssignAwardIn, admin_id: UUID
    ) -> RankingOut:
        award = await self._repo.get_award(award_id, organization_id)
        if award is None:
            raise NotFoundError("Premio no encontrado")
        row = await self._require_type(organization_id, award["staff_type_id"])
        _, event = await self._event_context(organization_id, body.event_id)
        assert event is not None  # noqa: S101 — event_id viene en el cuerpo
        (ctx,), _ = await self._contexts([row], event)
        if ctx.confirmed_at is not None:
            raise DomainError(
                ErrorCode.CONFLICT,
                "Los premios de este staff ya se confirmaron en este evento. "
                "Reábrelos para cambiarlos",
            )
        if (body.committee_id, body.position) not in ctx.slots(award):
            raise DomainError(ErrorCode.VALIDATION_ERROR, "Ese lugar no existe en este premio")
        suggested: UUID | None = None
        if body.candidate_id is not None:
            candidate = ctx.candidate_by_id.get(body.candidate_id)
            if candidate is None:
                raise NotFoundError("Ese candidato no es de este staff en este evento")
            if award["scope"] == "per_committee" and candidate["committee_id"] != body.committee_id:
                raise DomainError(ErrorCode.VALIDATION_ERROR, "El candidato es de otro comité")
            taken = any(
                a["candidate_id"] == body.candidate_id
                and a["award_id"] == award_id
                and (a["committee_id"], a["position"]) != (body.committee_id, body.position)
                for a in ctx.assignments
            )
            if taken:
                raise DomainError(ErrorCode.CONFLICT, "Ese candidato ya tiene este premio")
            for out in ctx.award_outs(with_slots=True):
                if out.id == award_id:
                    for slot in out.slots:
                        if (slot.committee_id, slot.position) == (body.committee_id, body.position):
                            suggested = slot.suggested_candidate_id or slot.candidate_id
        now = self._clock.now()
        await self._repo.upsert_assignment(
            {
                "award_id": award_id,
                "event_id": body.event_id,
                "committee_id": body.committee_id,
                "position": body.position,
                "candidate_id": body.candidate_id,
                "suggested_candidate_id": suggested,
                "override_reason": (body.override_reason or "").strip() or None,
                "assigned_by": admin_id if body.candidate_id else None,
                "assigned_at": now if body.candidate_id else None,
            }
        )
        return await self.ranking(
            organization_id,
            row["id"],
            body.event_id,
            body.committee_id if award["scope"] == "per_committee" else None,
        )

    async def confirm_awards(
        self, organization_id: UUID, type_id: UUID, body: ConfirmAwardsIn, admin_id: UUID
    ) -> StaffTypeDetailOut:
        row = await self._require_type(organization_id, type_id)
        _, event = await self._event_context(organization_id, body.event_id)
        if body.confirmed:
            (ctx,), _ = await self._contexts([row], event)
            awards = ctx.award_outs(with_slots=False)
            if not awards:
                raise DomainError(ErrorCode.CONFLICT, "Este staff no tiene premios que confirmar")
            missing = sum(a.slots_total - a.slots_assigned for a in awards)
            if missing:
                raise DomainError(
                    ErrorCode.CONFLICT,
                    f"Falta asignar {missing} premio{'s' if missing != 1 else ''}",
                )
            await self._repo.set_confirmation(type_id, body.event_id, self._clock.now(), admin_id)
        else:
            await self._repo.set_confirmation(type_id, body.event_id, None, None)
        return await self.detail(organization_id, type_id, body.event_id)

    # ------------------------------------------------------------ personas y miembros

    async def people(self, organization_id: UUID) -> list[PersonOut]:
        """Personas para «Añadir otra persona»: staff y jueces de la organización."""
        now = self._clock.now()
        staff = await self._repo.people(organization_id)
        emails = {(p["email"] or "").lower() for p in staff if p["email"]}
        out = [
            PersonOut(
                id=p["id"],
                full_name=p["full_name"],
                email=p["email"],
                title=p["title"],
                access=access_status(p, now),
                types=list(p["types"] or []),
                source="staff",
            )
            for p in staff
        ]
        out += [
            PersonOut(
                id=None,
                full_name=j["full_name"],
                email=j["email"],
                title="Juez",
                access="not_invited",
                types=[],
                source="judge",
            )
            for j in await self._repo.organization_judges(organization_id)
            if (j["email"] or "").lower() not in emails
        ]
        return out

    async def add_member(
        self,
        organization_id: UUID,
        type_id: UUID,
        body: MemberIn,
        event_id: UUID | None = None,
    ) -> StaffTypeDetailOut:
        await self._require_type(organization_id, type_id)
        committee_ids = await self._check_committees(organization_id, body.committee_ids)
        if body.person_id is not None:
            if await self._repo.get_person(body.person_id, organization_id) is None:
                raise NotFoundError("Persona no encontrada en la organización")
            person_id = body.person_id
        elif body.person is not None:
            existing = (
                await self._repo.person_by_email(organization_id, body.person.email)
                if body.person.email
                else None
            )
            if existing is not None:
                person_id = existing["id"]
            else:
                person_id = await self._repo.insert_person(
                    {
                        "organization_id": organization_id,
                        "full_name": body.person.full_name,
                        "email": body.person.email.lower() if body.person.email else None,
                        "title": body.person.title,
                    }
                )
        else:
            raise DomainError(ErrorCode.VALIDATION_ERROR, "Indica la persona a añadir")
        await self._repo.upsert_member(type_id, person_id, body.role, committee_ids)
        return await self.detail(organization_id, type_id, event_id)

    async def update_member(
        self,
        organization_id: UUID,
        member_id: UUID,
        body: MemberPatch,
        event_id: UUID | None = None,
    ) -> StaffTypeDetailOut:
        member = await self._repo.get_member(member_id, organization_id)
        if member is None:
            raise NotFoundError("Miembro no encontrado")
        data = body.model_dump(exclude_unset=True)
        values: dict[str, Any] = {}
        if data.get("role") is not None:
            values["role"] = data["role"]
        if data.get("committee_ids") is not None:
            values["committee_ids"] = await self._check_committees(
                organization_id, data["committee_ids"]
            )
        if data.get("evaluations_count") is not None:
            values["evaluations_count"] = data["evaluations_count"]
        if data.get("restore"):
            values["removed_at"] = None
            values["evaluations_count"] = True
        await self._repo.update_member(member_id, values)
        return await self.detail(organization_id, member["staff_type_id"], event_id)

    async def remove_member(
        self, organization_id: UUID, member_id: UUID, event_id: UUID | None = None
    ) -> StaffTypeDetailOut:
        """Quita al miembro sin borrar sus evaluaciones (siguen contando hasta que el admin
        diga lo contrario con `evaluations_count = false`)."""
        member = await self._repo.get_member(member_id, organization_id)
        if member is None:
            raise NotFoundError("Miembro no encontrado")
        if member["removed_at"] is None:
            await self._repo.update_member(member_id, {"removed_at": self._clock.now()})
        return await self.detail(organization_id, member["staff_type_id"], event_id)

    async def update_person(
        self, organization_id: UUID, person_id: UUID, body: PersonPatch
    ) -> PersonOut:
        person = await self._repo.get_person(person_id, organization_id)
        if person is None:
            raise NotFoundError("Persona no encontrada")
        data = body.model_dump(exclude_unset=True)
        values: dict[str, Any] = {}
        if data.get("full_name"):
            values["full_name"] = data["full_name"].strip()
        if "email" in data:
            email = (data["email"] or "").strip().lower() or None
            if email and email != (person["email"] or "").lower():
                other = await self._repo.person_by_email(organization_id, email)
                if other is not None and other["id"] != person_id:
                    raise DomainError(ErrorCode.CONFLICT, "Ese correo ya es de otra persona")
            values["email"] = email
        if "title" in data:
            values["title"] = (data["title"] or "").strip() or None
        await self._repo.update_person(person_id, values)
        refreshed = await self._repo.get_person(person_id, organization_id) or person
        return PersonOut(
            id=person_id,
            full_name=refreshed["full_name"],
            email=refreshed["email"],
            title=refreshed["title"],
            access=access_status(refreshed, self._clock.now()),
            types=[],
            source="staff",
        )

    async def issue_link(
        self, organization_id: UUID, person_id: UUID, body: AccessLinkIn
    ) -> AccessLinkOut:
        """Genera (o regenera) el enlace personal; el anterior deja de servir.

        Vence dos días después del último evento abierto de la organización (o en 30 días
        si no hay ninguno abierto).
        """
        person = await self._repo.get_person(person_id, organization_id)
        if person is None:
            raise NotFoundError("Persona no encontrada")
        now = self._clock.now()
        open_events = [
            e for e in await self._repo.events(organization_id) if e["status"] != "closed"
        ]
        expiry = (
            expires_at(max(e["ends_on"] for e in open_events))
            if open_events
            else now + LINK_DAYS_WITHOUT_EVENTS
        )
        expiry = max(expiry, now + timedelta(days=1))
        token = new_token()
        await self._repo.update_person(
            person_id,
            {
                "token_hash": hash_token(token),
                "token_issued_at": now,
                "token_expires_at": expiry,
                "last_used_at": None,
            },
        )
        return AccessLinkOut(
            person_id=person_id,
            full_name=person["full_name"],
            email=person["email"],
            token=token,
            url=f"{body.link_base}{token}",
            expires_at=expiry,
        )

    # ------------------------------------------------------------ miembro del staff (enlace)

    async def authenticate(self, token: str) -> StaffPerson:
        if not looks_like_token(token):
            raise DomainError(ErrorCode.UNAUTHORIZED, INVALID_LINK)
        person = await self._repo.person_by_token_hash(hash_token(token))
        now = self._clock.now()
        if person is None or (
            person["token_expires_at"] is not None and person["token_expires_at"] <= now
        ):
            raise DomainError(ErrorCode.UNAUTHORIZED, INVALID_LINK)
        last = person["last_used_at"]
        if last is None or now - last >= TOUCH_INTERVAL:
            await self._repo.update_person(person["id"], {"last_used_at": now})
        return StaffPerson(
            id=person["id"],
            organization_id=person["organization_id"],
            full_name=person["full_name"],
            title=person["title"],
            organization_name=person["organization_name"],
        )

    async def _open_events(self, organization_id: UUID) -> list[dict[str, Any]]:
        return [e for e in await self._repo.events(organization_id) if e["status"] != "closed"]

    async def me(self, person: StaffPerson) -> StaffMeOut:
        """Lo que le toca evaluar: por cada tipo de staff y evento no cerrado con candidatos."""
        rows = await self._repo.person_types(person.id)
        events = await self._open_events(person.organization_id)
        evaluations = {
            (e["member_id"], e["candidate_id"]): e
            for e in await self._repo.evaluations([r["member_id"] for r in rows])
        }
        assignments: list[StaffAssignmentOut] = []
        for event in events:
            committees = await self._repo.event_committees(event["id"])
            confirmations = await self._repo.confirmations([r["id"] for r in rows], event["id"])
            for r in rows:
                candidates = (
                    _member_candidates(
                        r,
                        await self._repo.candidates(
                            event["id"], r["evaluates"], _scope(r, committees)
                        ),
                    )
                    if r["evaluates"]
                    else []
                )
                if not candidates and r["evaluates"] is not None:
                    continue  # este tipo no tiene candidatos para la persona en este evento
                rubric = _rubric(r)
                reason = _closed_reason(r, confirmations.get(r["id"]))
                items = []
                for c in candidates:
                    ev = evaluations.get((r["member_id"], c["candidate_id"]))
                    values = values_from_json(ev["values"]) if ev else {}
                    items.append(
                        StaffCandidateOut(
                            candidate_id=c["candidate_id"],
                            label=c["label"],
                            sublabel=c["sublabel"],
                            committee_acronym=c["committee_acronym"],
                            values={k: float(v) for k, v in values.items()},
                            comment=ev["comment"] if ev else None,
                            complete=evaluation_score(rubric, values) is not None,
                            updated_at=(ev["updated_at"] or ev["created_at"]) if ev else None,
                        )
                    )
                assignments.append(
                    StaffAssignmentOut(
                        member_id=r["member_id"],
                        event_id=event["id"],
                        event_name=event["name"],
                        staff_type_id=r["id"],
                        name=r["name"],
                        code=r["code"],
                        color=r["color"],
                        role=r["role"],
                        evaluates=r["evaluates"],
                        open=reason is None,
                        closed_reason=reason,
                        scale_min=float(r["scale_min"]),
                        scale_max=float(r["scale_max"]),
                        scale_step=float(r["scale_step"]),
                        criteria=_criteria_out(r),
                        candidates=items,
                    )
                )
        return StaffMeOut(
            full_name=person.full_name,
            title=person.title,
            organization_name=person.organization_name,
            assignments=assignments,
        )

    async def save_evaluation(
        self, person: StaffPerson, body: StaffEvaluationIn
    ) -> StaffEvaluationOut:
        row = next(
            (
                r
                for r in await self._repo.person_types(person.id)
                if r["member_id"] == body.member_id
            ),
            None,
        )
        if row is None:
            raise DomainError(ErrorCode.FORBIDDEN, "No perteneces a este staff")
        event = next(
            (
                e
                for e in await self._open_events(person.organization_id)
                if e["id"] == body.event_id
            ),
            None,
        )
        if event is None:
            raise DomainError(ErrorCode.EVENT_CLOSED, "El evento está cerrado o no existe")
        reason = _closed_reason(row, await self._confirmed_at(row["id"], event["id"]))
        if reason is not None:
            raise DomainError(ErrorCode.CONFLICT, reason)
        committees = await self._repo.event_committees(event["id"])
        candidates = _member_candidates(
            row,
            await self._repo.candidates(event["id"], row["evaluates"], _scope(row, committees)),
        )
        if body.candidate_id not in {c["candidate_id"] for c in candidates}:
            raise DomainError(ErrorCode.FORBIDDEN, "Ese candidato no te toca evaluar")
        rubric = _rubric(row)
        criterion_ids = {c.id for c in rubric.criteria}
        step = Decimal(row["scale_step"])
        clean: dict[str, float] = {}
        for key, value in body.values.items():
            if key not in criterion_ids:
                raise DomainError(ErrorCode.VALIDATION_ERROR, "Criterio desconocido")
            if not rubric.scale_min <= value <= rubric.scale_max:
                raise DomainError(
                    ErrorCode.VALUE_OUT_OF_RANGE,
                    f"El valor debe estar entre {rubric.scale_min:f} y {rubric.scale_max:f}",
                )
            if (value - rubric.scale_min) % step != 0:
                raise DomainError(
                    ErrorCode.VALUE_OUT_OF_RANGE,
                    f"El valor debe ir en pasos de {step.normalize():f}",
                )
            clean[key] = float(value)
        saved = await self._repo.upsert_evaluation(
            body.member_id,
            body.candidate_id,
            clean,
            (body.comment or "").strip() or None,
            body.client_updated_at,
        )
        values = values_from_json(saved["values"])
        return StaffEvaluationOut(
            candidate_id=body.candidate_id,
            values={k: float(v) for k, v in values.items()},
            comment=saved["comment"],
            complete=evaluation_score(rubric, values) is not None,
            updated_at=saved["updated_at"] or saved["created_at"],
        )
