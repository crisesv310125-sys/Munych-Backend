from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from munych_api.modules.results.application.ports import PublicResult, ScoreDetail
from munych_api.modules.results.domain.models import (
    Award,
    CommitteeData,
    CommitteeInfo,
    CriterionInfo,
    DelegateInfo,
    DelegationInfo,
    EventInfo,
    PeerVoteValue,
    PublicationSettings,
    RubricInfo,
    ScoreValue,
    SessionInfo,
    SpecialAward,
)
from munych_api.scoring_engine.staff import (
    StaffEvaluation,
    average_types,
    candidate_results,
    group_scores,
    rubric_from_json,
    values_from_json,
)
from munych_api.shared.database.tables import (
    awards,
    committee_judges,
    committees,
    criteria,
    delegates,
    delegations,
    events,
    judges,
    peer_votes,
    public_results,
    result_snapshots,
    rubrics,
    scores,
    scoring_sessions,
    staff_award_assignments,
    staff_award_confirmations,
    staff_awards,
    staff_evaluations,
    staff_members,
    staff_types,
)
from munych_api.shared.kernel.catalog import EVENT_TYPES, VoterRole


class SqlAlchemyResultsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------ comités y premios

    async def committee_data(
        self, committee_id: UUID, organization_id: UUID
    ) -> CommitteeData | None:
        row = (
            await self._session.execute(
                select(
                    committees,
                    events.c.status.label("event_status"),
                    events.c.event_type,
                    func.coalesce(committees.c.rubric_id, events.c.default_rubric_id).label(
                        "effective_rubric_id"
                    ),
                )
                .join(events, events.c.id == committees.c.event_id)
                .where(committees.c.id == committee_id, events.c.organization_id == organization_id)
            )
        ).first()
        if row is None:
            return None

        rubric = None
        rubric_row = (
            await self._session.execute(
                select(rubrics.c.scale_min, rubrics.c.scale_max).where(
                    rubrics.c.id == row.effective_rubric_id
                )
            )
        ).first()
        if rubric_row is not None:
            criterion_rows = await self._session.execute(
                select(criteria.c.id, criteria.c.name, criteria.c.weight, criteria.c.position)
                .where(criteria.c.rubric_id == row.effective_rubric_id)
                .order_by(criteria.c.position)
            )
            rubric = RubricInfo(
                scale_min=rubric_row.scale_min,
                scale_max=rubric_row.scale_max,
                criteria=tuple(
                    CriterionInfo(c.id, c.name, Decimal(c.weight), c.position)
                    for c in criterion_rows
                ),
            )

        session_rows = await self._session.execute(
            select(scoring_sessions.c.id, scoring_sessions.c.number)
            .where(scoring_sessions.c.committee_id == committee_id)
            .order_by(scoring_sessions.c.number)
        )
        delegation_rows = (
            await self._session.execute(
                select(delegations)
                .where(delegations.c.committee_id == committee_id)
                .order_by(delegations.c.country_code.nulls_last(), delegations.c.character_name)
            )
        ).all()
        delegate_rows = await self._session.execute(
            select(delegates.c.id, delegates.c.delegation_id, delegates.c.full_name)
            .join(delegations, delegations.c.id == delegates.c.delegation_id)
            .where(delegations.c.committee_id == committee_id)
            .order_by(delegates.c.created_at, delegates.c.id)
        )
        by_delegation: dict[UUID, list[DelegateInfo]] = defaultdict(list)
        for d in delegate_rows:
            by_delegation[d.delegation_id].append(DelegateInfo(d.id, d.full_name))

        score_rows = await self._session.execute(
            select(
                scores.c.judge_id,
                scores.c.delegate_id,
                scores.c.session_id,
                scores.c.criterion_id,
                scores.c.value,
                committee_judges.c.role.label("committee_role"),
            )
            .join(scoring_sessions, scoring_sessions.c.id == scores.c.session_id)
            .outerjoin(
                committee_judges,
                (committee_judges.c.committee_id == scoring_sessions.c.committee_id)
                & (committee_judges.c.judge_id == scores.c.judge_id),
            )
            .where(scoring_sessions.c.committee_id == committee_id)
        )
        vote_rows = await self._session.execute(
            select(
                peer_votes.c.voter_delegate_id,
                peer_votes.c.delegation_id,
                peer_votes.c.award_type,
            ).where(peer_votes.c.committee_id == committee_id)
        )

        return CommitteeData(
            committee=CommitteeInfo(
                id=row.id,
                event_id=row.event_id,
                slug=row.slug,
                name=row.name,
                acronym=row.acronym,
                type=row.type,
                award_quotas=dict(row.award_quotas or {}),
                event_closed=row.event_status == "closed",
            ),
            rubric=rubric,
            sessions=tuple(SessionInfo(s.id, s.number) for s in session_rows),
            delegations=tuple(
                DelegationInfo(
                    id=d.id,
                    country_code=d.country_code,
                    character_name=d.character_name,
                    institution=d.institution,
                    delegates=tuple(by_delegation[d.id]),
                )
                for d in delegation_rows
            ),
            scores=tuple(
                ScoreValue(
                    s.judge_id,
                    s.delegate_id,
                    s.session_id,
                    s.criterion_id,
                    s.value,
                    s.committee_role,
                )
                for s in score_rows
            ),
            event_type=row.event_type,
            peer_votes=tuple(
                PeerVoteValue(v.voter_delegate_id, v.delegation_id, v.award_type) for v in vote_rows
            ),
            tiebreak_order=tuple(row.tiebreak_order or ()),
            staff_role_scores=await self._staff_role_scores(
                organization_id,
                committee_id,
                row.event_type,
                {d.id: [p.id for p in by_delegation[d.id]] for d in delegation_rows},
            ),
        )

    async def _staff_role_scores(
        self,
        organization_id: UUID,
        committee_id: UUID,
        event_type: str,
        delegates_of: dict[UUID, list[UUID]],
    ) -> dict[VoterRole, dict[UUID, Decimal | None]]:
        """Nota por delegación de los tipos de staff que cuentan en el ranking.

        Los tipos de staff son de la organización; los candidatos (y por tanto las
        evaluaciones que cuentan) son los de este comité. Solo los tipos configurados,
        con rúbrica válida, cuyo alcance incluye el comité y cuyo peso existe en el tipo
        de evento. Los tipos que evalúan delegados aportan el promedio de los delegados
        de la delegación; varios tipos del mismo peso se promedian.
        """
        weights = EVENT_TYPES[event_type].voter_weights  # type: ignore[index]
        type_rows = [
            t
            for t in (
                await self._session.execute(
                    select(staff_types).where(
                        staff_types.c.organization_id == organization_id,
                        staff_types.c.archived_at.is_(None),
                        staff_types.c.counts_as.in_(("staff", "chair")),
                        staff_types.c.evaluates.is_not(None),
                    )
                )
            ).mappings()
            if t["counts_as"] in weights
            and (t["all_committees"] or committee_id in (t["committee_ids"] or []))
        ]
        per_role: dict[VoterRole, list[dict[str, Decimal | None]]] = defaultdict(list)
        delegation_of = {p: d for d, people in delegates_of.items() for p in people}
        for t in type_rows:
            rubric = rubric_from_json(t["scale_min"], t["scale_max"], t["criteria"] or [])
            if not rubric.valid:
                continue
            evaluations = await self._session.execute(
                select(staff_evaluations.c.member_id, staff_evaluations.c.candidate_id)
                .add_columns(staff_evaluations.c["values"])
                .join(staff_members, staff_members.c.id == staff_evaluations.c.member_id)
                .where(
                    staff_members.c.staff_type_id == t["id"],
                    (staff_members.c.removed_at.is_(None))
                    | staff_members.c.evaluations_count.is_(True),
                )
            )
            by_person = t["evaluates"] in ("delegates", "press")
            candidates = list(delegation_of) if by_person else list(delegates_of)
            results = candidate_results(
                rubric,
                (
                    StaffEvaluation(str(e.member_id), str(e.candidate_id), values_from_json(e[2]))
                    for e in evaluations
                ),
                [str(c) for c in candidates],
                1,
            )
            scores = {r.candidate_id: r.score for r in results}
            if by_person:
                by_delegation = group_scores(
                    scores, {str(d): [str(p) for p in ps] for d, ps in delegates_of.items()}
                )
            else:
                by_delegation = {str(d): scores.get(str(d)) for d in delegates_of}
            per_role[t["counts_as"]].append(by_delegation)
        return {
            role: {UUID(k): v for k, v in average_types(maps).items()}
            for role, maps in per_role.items()
        }

    async def set_tiebreak_order(self, committee_id: UUID, order: list[UUID]) -> None:
        await self._session.execute(
            update(committees)
            .where(committees.c.id == committee_id)
            .values(tiebreak_order=order, updated_at=func.now())
        )

    async def get_awards(self, committee_id: UUID) -> list[Award]:
        rows = await self._session.execute(
            select(awards.c.award_type, awards.c.delegation_id, awards.c.position).where(
                awards.c.committee_id == committee_id
            )
        )
        return [Award(r.award_type, r.delegation_id, r.position) for r in rows]

    async def replace_awards(
        self, committee_id: UUID, items: list[Award], assigned_by: UUID, assigned_at: datetime
    ) -> None:
        await self._session.execute(delete(awards).where(awards.c.committee_id == committee_id))
        if items:
            await self._session.execute(
                insert(awards),
                [
                    {
                        "committee_id": committee_id,
                        "award_type": a.award_type,
                        "delegation_id": a.delegation_id,
                        "position": a.position,
                        "assigned_by": assigned_by,
                        "assigned_at": assigned_at,
                    }
                    for a in items
                ],
            )

    # ------------------------------------------------------------ eventos

    async def get_event(self, event_id: UUID, organization_id: UUID) -> EventInfo | None:
        row = (
            await self._session.execute(
                select(events).where(
                    events.c.id == event_id, events.c.organization_id == organization_id
                )
            )
        ).first()
        if row is None:
            return None
        return EventInfo(
            id=row.id,
            slug=row.slug,
            name=row.name,
            brand=row.brand,
            logo_path=row.logo_path,
            venue=row.venue,
            timezone=row.timezone,
            starts_on=row.starts_on,
            ends_on=row.ends_on,
            status=row.status,
            publication_settings=PublicationSettings.from_dict(row.publication_settings),
        )

    async def committee_ids(self, event_id: UUID) -> list[UUID]:
        rows = await self._session.execute(
            select(committees.c.id)
            .where(committees.c.event_id == event_id)
            .order_by(committees.c.name, committees.c.id)
        )
        return [r[0] for r in rows]

    async def open_sessions_count(self, event_id: UUID) -> int:
        count = await self._session.scalar(
            select(func.count())
            .select_from(scoring_sessions)
            .join(committees, committees.c.id == scoring_sessions.c.committee_id)
            .where(committees.c.event_id == event_id, scoring_sessions.c.status == "open")
        )
        return int(count or 0)

    async def close_event(self, event_id: UUID) -> None:
        await self._session.execute(
            update(events).where(events.c.id == event_id).values(status="closed")
        )

    async def insert_snapshot(
        self, event_id: UUID, data: dict[str, Any], created_by: UUID
    ) -> tuple[UUID, datetime]:
        row = (
            await self._session.execute(
                insert(result_snapshots)
                .values(event_id=event_id, data=data, created_by=created_by)
                .returning(result_snapshots.c.id, result_snapshots.c.created_at)
            )
        ).one()
        return row.id, row.created_at

    async def latest_snapshot(self, event_id: UUID) -> dict[str, Any] | None:
        data = await self._session.scalar(
            select(result_snapshots.c.data)
            .where(result_snapshots.c.event_id == event_id)
            .order_by(result_snapshots.c.created_at.desc())
            .limit(1)
        )
        return dict(data) if data is not None else None

    async def score_details(self, event_id: UUID) -> list[ScoreDetail]:
        rows = await self._session.execute(
            select(
                committees.c.id.label("committee_id"),
                committees.c.name.label("committee"),
                func.coalesce(delegations.c.country_code, delegations.c.character_name).label(
                    "delegation"
                ),
                delegates.c.full_name.label("delegate"),
                func.coalesce(delegates.c.institution, delegations.c.institution).label(
                    "institution"
                ),
                scoring_sessions.c.number.label("session_number"),
                judges.c.full_name.label("judge"),
                criteria.c.name.label("criterion"),
                criteria.c.position.label("criterion_position"),
                scores.c.value,
                scores.c.comment,
                func.coalesce(scores.c.updated_at, scores.c.created_at).label("updated_at"),
            )
            .select_from(scores)
            .join(delegates, delegates.c.id == scores.c.delegate_id)
            .join(delegations, delegations.c.id == delegates.c.delegation_id)
            .join(committees, committees.c.id == delegations.c.committee_id)
            .join(scoring_sessions, scoring_sessions.c.id == scores.c.session_id)
            .join(judges, judges.c.user_id == scores.c.judge_id)
            .join(criteria, criteria.c.id == scores.c.criterion_id)
            .where(committees.c.event_id == event_id)
            .order_by(
                committees.c.name,
                delegations.c.country_code.nulls_last(),
                delegations.c.character_name,
                delegates.c.full_name,
                scoring_sessions.c.number,
                judges.c.full_name,
                criteria.c.position,
            )
        )
        return [
            ScoreDetail(
                committee_id=r.committee_id,
                committee=r.committee,
                delegation=r.delegation or "",
                delegate=r.delegate,
                institution=r.institution,
                session_number=r.session_number,
                judge=r.judge,
                criterion=r.criterion,
                value=r.value,
                comment=r.comment,
                updated_at=r.updated_at,
            )
            for r in rows
        ]

    # ------------------------------------------------------------ premios especiales (staff)

    async def special_awards(self, event_id: UUID) -> list[SpecialAward]:
        """Premios de los tipos de staff de la organización **confirmados** en el evento."""
        organization_id = await self._session.scalar(
            select(events.c.organization_id).where(events.c.id == event_id)
        )
        if organization_id is None:
            return []
        type_rows = {
            t["id"]: t
            for t in (
                await self._session.execute(
                    select(staff_types)
                    .join(
                        staff_award_confirmations,
                        (staff_award_confirmations.c.staff_type_id == staff_types.c.id)
                        & (staff_award_confirmations.c.event_id == event_id),
                    )
                    .where(
                        staff_types.c.organization_id == organization_id,
                        staff_types.c.archived_at.is_(None),
                        staff_award_confirmations.c.confirmed_at.is_not(None),
                    )
                )
            ).mappings()
        }
        if not type_rows:
            return []
        award_rows = {
            a["id"]: a
            for a in (
                await self._session.execute(
                    select(staff_awards).where(
                        staff_awards.c.staff_type_id.in_(list(type_rows)),
                        staff_awards.c.archived_at.is_(None),
                    )
                )
            ).mappings()
        }
        assignment_rows = (
            (
                await self._session.execute(
                    select(staff_award_assignments).where(
                        staff_award_assignments.c.award_id.in_(list(award_rows)),
                        staff_award_assignments.c.event_id == event_id,
                        staff_award_assignments.c.candidate_id.is_not(None),
                    )
                )
            )
            .mappings()
            .all()
            if award_rows
            else []
        )
        if not assignment_rows:
            return []
        candidates = await self._special_candidates([a["candidate_id"] for a in assignment_rows])
        scores = await self._staff_candidate_scores(type_rows, list(candidates))

        out: list[tuple[tuple[Any, ...], SpecialAward]] = []
        for a in assignment_rows:
            award = award_rows[a["award_id"]]
            staff_type = type_rows[award["staff_type_id"]]
            candidate = candidates.get(a["candidate_id"])
            if candidate is None:  # el candidato ya no existe
                continue
            special = SpecialAward(
                staff_type=staff_type["name"],
                award=award["name"],
                position=a["position"],
                committee_acronym=candidate["committee_acronym"],
                country_code=candidate["country_code"],
                character_name=candidate["character_name"],
                delegates=tuple(candidate["delegates"]),
                institution=candidate["institution"],
                score=scores.get((staff_type["id"], a["candidate_id"])),
                winners=award["winners"],
            )
            key = (
                staff_type["position"],
                staff_type["name"],
                award["position"],
                candidate["committee_acronym"] or "",
                a["position"],
            )
            out.append((key, special))
        return [s for _, s in sorted(out, key=lambda pair: pair[0])]

    async def _special_candidates(self, ids: list[UUID]) -> dict[UUID, dict[str, Any]]:
        """Candidato → delegación, delegados, institución y comité. Sirve para los dos tipos
        de candidato: delegación (todos sus delegados) o delegado (solo él)."""
        out: dict[UUID, dict[str, Any]] = {}
        base = select(
            delegations.c.id.label("delegation_id"),
            delegations.c.country_code,
            delegations.c.character_name,
            delegations.c.institution,
            committees.c.acronym.label("committee_acronym"),
        ).join(committees, committees.c.id == delegations.c.committee_id)
        for d in (await self._session.execute(base.where(delegations.c.id.in_(ids)))).mappings():
            names: list[str] = list(
                await self._session.scalars(
                    select(delegates.c.full_name)
                    .where(delegates.c.delegation_id == d["delegation_id"])
                    .order_by(delegates.c.created_at, delegates.c.id)
                )
            )
            out[d["delegation_id"]] = {**d, "delegates": list(names)}
        person_rows = await self._session.execute(
            base.add_columns(
                delegates.c.id.label("delegate_id"),
                delegates.c.full_name,
                delegates.c.institution.label("delegate_institution"),
            )
            .join(delegates, delegates.c.delegation_id == delegations.c.id)
            .where(delegates.c.id.in_(ids))
        )
        for d in person_rows.mappings():
            out[d["delegate_id"]] = {
                **d,
                "institution": d["delegate_institution"] or d["institution"],
                "delegates": [d["full_name"]],
            }
        return out

    async def _staff_candidate_scores(
        self, type_rows: dict[UUID, Any], candidate_ids: list[UUID]
    ) -> dict[tuple[UUID, UUID], Decimal | None]:
        """Nota 0-100 de cada candidato premiado en la rúbrica de su tipo de staff."""
        rows = await self._session.execute(
            select(
                staff_members.c.staff_type_id,
                staff_evaluations.c.member_id,
                staff_evaluations.c.candidate_id,
            )
            .add_columns(staff_evaluations.c["values"])
            .join(staff_members, staff_members.c.id == staff_evaluations.c.member_id)
            .where(
                staff_members.c.staff_type_id.in_(list(type_rows)),
                staff_evaluations.c.candidate_id.in_(candidate_ids),
                (staff_members.c.removed_at.is_(None))
                | staff_members.c.evaluations_count.is_(True),
            )
        )
        by_type: dict[UUID, list[StaffEvaluation]] = defaultdict(list)
        for r in rows:
            by_type[r[0]].append(StaffEvaluation(str(r[1]), str(r[2]), values_from_json(r[3])))
        out: dict[tuple[UUID, UUID], Decimal | None] = {}
        for type_id, t in type_rows.items():
            rubric = rubric_from_json(t["scale_min"], t["scale_max"], t["criteria"] or [])
            for result in candidate_results(
                rubric, by_type[type_id], [str(c) for c in candidate_ids], 1
            ):
                out[type_id, UUID(result.candidate_id)] = result.score
        return out

    # ------------------------------------------------------------ publicación

    async def save_publication_settings(
        self, event_id: UUID, settings: PublicationSettings
    ) -> None:
        await self._session.execute(
            update(events)
            .where(events.c.id == event_id)
            .values(publication_settings=settings.to_dict())
        )

    async def get_public_result(self, event_id: UUID) -> PublicResult | None:
        row = (
            await self._session.execute(
                select(public_results).where(public_results.c.event_id == event_id)
            )
        ).first()
        if row is None:
            return None
        return PublicResult(
            version=row.version,
            published=row.published,
            published_at=row.published_at,
            data=dict(row.data),
        )

    async def upsert_public_result(
        self,
        *,
        event_id: UUID,
        event_slug: str,
        version: int,
        data: dict[str, Any],
        published_at: datetime,
    ) -> None:
        stmt = pg_insert(public_results).values(
            event_slug=event_slug,
            event_id=event_id,
            published=True,
            version=version,
            data=data,
            published_at=published_at,
        )
        await self._session.execute(
            stmt.on_conflict_do_update(
                index_elements=[public_results.c.event_id],
                set_={
                    "event_slug": stmt.excluded.event_slug,
                    "published": True,
                    "version": stmt.excluded.version,
                    "data": stmt.excluded.data,
                    "published_at": stmt.excluded.published_at,
                },
            )
        )

    async def unpublish(self, event_id: UUID) -> bool:
        result = await self._session.execute(
            update(public_results)
            .where(public_results.c.event_id == event_id)
            .values(published=False)
            .returning(public_results.c.event_id)
        )
        return result.first() is not None

    async def commit(self) -> None:
        await self._session.commit()
