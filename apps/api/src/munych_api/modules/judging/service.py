from decimal import Decimal
from typing import Any
from uuid import UUID

from munych_api.modules.judging.repository import JudgingRepository
from munych_api.modules.judging.schemas import (
    AssignmentIn,
    AssignmentOut,
    JudgeCommitteeDetailOut,
    JudgeCommitteeOut,
    JudgeCriterionOut,
    JudgeDelegateOut,
    JudgeDelegationOut,
    JudgeEventOut,
    JudgeRubricOut,
    JudgeSessionOut,
)
from munych_api.shared.kernel import DomainError, ErrorCode, NotFoundError
from munych_api.shared.kernel.catalog import EVENT_LOGOS_BUCKET
from munych_api.shared.supabase import ObjectStorage


class JudgingService:
    def __init__(self, repository: JudgingRepository, storage: ObjectStorage) -> None:
        self._repo = repository
        self._storage = storage

    def _logo_url(self, logo_path: str | None) -> str | None:
        return self._storage.public_url(EVENT_LOGOS_BUCKET, logo_path) if logo_path else None

    # ------------------------------------------------------------ asignaciones (admin)

    async def _require_committee(self, organization_id: UUID, committee_id: UUID) -> dict[str, Any]:
        committee = await self._repo.get_committee(committee_id, organization_id)
        if committee is None:
            raise NotFoundError("Comité no encontrado")
        return committee

    async def list_assignments(
        self, organization_id: UUID, committee_id: UUID
    ) -> list[AssignmentOut]:
        await self._require_committee(organization_id, committee_id)
        return [AssignmentOut(**r) for r in await self._repo.list_assignments(committee_id)]

    async def replace_assignments(
        self, organization_id: UUID, committee_id: UUID, assignments: list[AssignmentIn]
    ) -> list[AssignmentOut]:
        committee = await self._require_committee(organization_id, committee_id)
        if committee["event_status"] == "closed":
            raise DomainError(ErrorCode.EVENT_CLOSED, "El evento está cerrado")

        judge_ids = [a.judge_id for a in assignments]
        if len(judge_ids) != len(set(judge_ids)):
            raise DomainError(ErrorCode.VALIDATION_ERROR, "Hay jueces repetidos en la lista")
        unknown = set(judge_ids) - await self._repo.existing_judges(judge_ids, organization_id)
        if unknown:
            raise NotFoundError("Algún juez no existe en la organización")

        await self._repo.replace_assignments(
            committee_id, [(a.judge_id, a.role) for a in assignments]
        )
        # Quien califica en un comité forma parte del evento.
        await self._repo.add_judges_to_event(committee["event_id"], judge_ids)
        return await self.list_assignments(organization_id, committee_id)

    # ------------------------------------------------------------ panel del juez

    async def judge_committees(self, judge_id: UUID) -> list[JudgeCommitteeOut]:
        return [
            JudgeCommitteeOut(
                committee_id=r["committee_id"],
                name=r["name"],
                acronym=r["acronym"],
                role=r["role"],
                event=JudgeEventOut(
                    name=r["event_name"],
                    logo_url=self._logo_url(r["logo_path"]),
                    timezone=r["timezone"],
                ),
            )
            for r in await self._repo.judge_committees(judge_id)
        ]

    async def judge_committee_detail(
        self, committee_id: UUID, role: str
    ) -> JudgeCommitteeDetailOut:
        """Datos del comité para calificar. La asignación ya se comprobó en el router."""
        committee = await self._repo.committee_detail(committee_id)
        if committee is None:  # pragma: no cover — la asignación implica que existe
            raise NotFoundError("Comité no encontrado")

        delegations: dict[UUID, JudgeDelegationOut] = {}
        for row in await self._repo.delegations_with_delegates(committee_id):
            delegation = delegations.setdefault(
                row["id"],
                JudgeDelegationOut(
                    delegation_id=row["id"],
                    country_code=row["country_code"],
                    character_name=row["character_name"],
                    institution=row["institution"],
                    delegates=[],
                ),
            )
            if row["delegate_id"] is not None:
                delegation.delegates.append(
                    JudgeDelegateOut(delegate_id=row["delegate_id"], full_name=row["full_name"])
                )

        rubric_id = committee["rubric_id"] or committee["default_rubric_id"]
        rubric_row = await self._repo.rubric(rubric_id) if rubric_id else None
        rubric = None
        if rubric_row is not None:
            rubric = JudgeRubricOut(
                id=rubric_row["id"],
                name=rubric_row["name"],
                scale_min=rubric_row["scale_min"],
                scale_max=rubric_row["scale_max"],
                criteria=[
                    JudgeCriterionOut(
                        id=c["id"],
                        name=c["name"],
                        description=c["description"],
                        weight=float(Decimal(c["weight"])),
                        position=c["position"],
                        level_descriptors=c["level_descriptors"] or {},
                    )
                    for c in await self._repo.criteria(rubric_row["id"])
                ],
            )

        return JudgeCommitteeDetailOut(
            committee_id=committee["id"],
            name=committee["name"],
            acronym=committee["acronym"],
            type=committee["type"],
            delegation_mode=committee["delegation_mode"],
            role=role,  # type: ignore[arg-type]
            event=JudgeEventOut(
                name=committee["event_name"],
                logo_url=self._logo_url(committee["logo_path"]),
                timezone=committee["timezone"],
            ),
            event_closed=committee["event_status"] == "closed",
            delegations=list(delegations.values()),
            rubric=rubric,
            sessions=[
                JudgeSessionOut(
                    session_id=s["id"],
                    number=s["number"],
                    status=s["status"],
                    opened_at=s["opened_at"],
                    closed_at=s["closed_at"],
                )
                for s in await self._repo.sessions(committee_id)
            ],
        )
