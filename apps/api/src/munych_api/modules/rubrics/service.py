from decimal import Decimal
from typing import Any
from uuid import UUID

from munych_api.modules.rubrics.repository import RubricsRepository
from munych_api.modules.rubrics.schemas import CriterionIn, CriterionOut, RubricIn, RubricOut
from munych_api.modules.rubrics.validation import validate_rubric
from munych_api.shared.kernel import DomainError, ErrorCode, NotFoundError
from munych_api.shared.kernel.catalog import (
    DEFAULT_CRITERIA,
    DEFAULT_LEVEL_DESCRIPTORS,
    DEFAULT_RUBRIC_NAME,
    DEFAULT_SCALE,
)


def default_rubric() -> RubricIn:
    """Rúbrica por defecto de la sección 6.1 (escala 1–4)."""
    return RubricIn(
        name=DEFAULT_RUBRIC_NAME,
        scale_min=DEFAULT_SCALE[0],
        scale_max=DEFAULT_SCALE[1],
        criteria=[
            CriterionIn(name=name, weight=weight, level_descriptors=dict(DEFAULT_LEVEL_DESCRIPTORS))
            for name, weight in DEFAULT_CRITERIA
        ],
    )


def _criterion_values(criterion: CriterionIn, position: int) -> dict[str, Any]:
    return {
        "name": criterion.name.strip(),
        "description": criterion.description,
        "weight": criterion.weight,
        "position": position,
        "level_descriptors": criterion.level_descriptors,
    }


class RubricsService:
    def __init__(self, repository: RubricsRepository) -> None:
        self._repo = repository

    async def _to_out(self, rubric_rows: list[dict[str, Any]]) -> list[RubricOut]:
        criteria_rows = await self._repo.list_criteria([r["id"] for r in rubric_rows])
        by_rubric: dict[UUID, list[CriterionOut]] = {r["id"]: [] for r in rubric_rows}
        for c in criteria_rows:
            by_rubric[c["rubric_id"]].append(
                CriterionOut(
                    id=c["id"],
                    name=c["name"],
                    description=c["description"],
                    weight=float(Decimal(c["weight"])),
                    position=c["position"],
                    level_descriptors=c["level_descriptors"] or {},
                )
            )
        return [
            RubricOut(
                id=r["id"],
                event_id=r["event_id"],
                name=r["name"],
                scale_min=r["scale_min"],
                scale_max=r["scale_max"],
                criteria=by_rubric[r["id"]],
            )
            for r in rubric_rows
        ]

    async def _require_event(self, event_id: UUID, organization_id: UUID) -> dict[str, Any]:
        event = await self._repo.get_event(event_id, organization_id)
        if event is None:
            raise NotFoundError("Evento no encontrado")
        return event

    async def _require_rubric(self, rubric_id: UUID, organization_id: UUID) -> dict[str, Any]:
        rubric = await self._repo.get_rubric(rubric_id, organization_id)
        if rubric is None:
            raise NotFoundError("Rúbrica no encontrada")
        return rubric

    async def create_rubric_for_event(self, event_id: UUID, data: RubricIn) -> UUID:
        """Crea la rúbrica sin comprobar permisos (uso interno de otros módulos)."""
        validate_rubric(data)
        rubric_id = await self._repo.create_rubric(
            event_id, data.name.strip(), data.scale_min, data.scale_max
        )
        for position, criterion in enumerate(data.criteria, start=1):
            await self._repo.insert_criterion(rubric_id, _criterion_values(criterion, position))
        return rubric_id

    async def create_rubric(
        self, organization_id: UUID, event_id: UUID, data: RubricIn
    ) -> RubricOut:
        event = await self._require_event(event_id, organization_id)
        if event["status"] == "closed":
            raise DomainError(ErrorCode.EVENT_CLOSED, "El evento está cerrado")
        if any(c.id is not None for c in data.criteria):
            raise DomainError(
                ErrorCode.VALIDATION_ERROR, "Una rúbrica nueva no puede reutilizar criterios"
            )
        rubric_id = await self.create_rubric_for_event(event_id, data)
        return await self.get_rubric(organization_id, rubric_id)

    async def list_rubrics(self, organization_id: UUID, event_id: UUID) -> list[RubricOut]:
        await self._require_event(event_id, organization_id)
        return await self._to_out(await self._repo.list_rubrics(event_id))

    async def get_rubric(self, organization_id: UUID, rubric_id: UUID) -> RubricOut:
        rubric = await self._require_rubric(rubric_id, organization_id)
        return (await self._to_out([rubric]))[0]

    async def replace_rubric(
        self, organization_id: UUID, rubric_id: UUID, data: RubricIn
    ) -> RubricOut:
        rubric = await self._require_rubric(rubric_id, organization_id)
        if rubric["event_status"] == "closed":
            raise DomainError(ErrorCode.EVENT_CLOSED, "El evento está cerrado")
        validate_rubric(data)

        existing_ids = {c["id"] for c in await self._repo.list_criteria([rubric_id])}
        incoming_ids = {c.id for c in data.criteria if c.id is not None}
        unknown = incoming_ids - existing_ids
        if unknown:
            raise NotFoundError("Algún criterio no pertenece a esta rúbrica")

        scale_changed = (data.scale_min, data.scale_max) != (
            rubric["scale_min"],
            rubric["scale_max"],
        )
        if scale_changed and await self._repo.rubric_has_scores(rubric_id):
            raise DomainError(
                ErrorCode.CONFLICT,
                "No se puede cambiar la escala: la rúbrica ya tiene calificaciones",
            )

        removed = list(existing_ids - incoming_ids)
        if await self._repo.criteria_with_scores(removed):
            raise DomainError(
                ErrorCode.CONFLICT,
                "No se puede eliminar un criterio que ya tiene calificaciones",
            )

        await self._repo.update_rubric(
            rubric_id,
            {"name": data.name.strip(), "scale_min": data.scale_min, "scale_max": data.scale_max},
        )
        await self._repo.delete_criteria(removed)
        for position, criterion in enumerate(data.criteria, start=1):
            values = _criterion_values(criterion, position)
            if criterion.id is None:
                await self._repo.insert_criterion(rubric_id, values)
            else:
                await self._repo.update_criterion(criterion.id, values)
        return await self.get_rubric(organization_id, rubric_id)
