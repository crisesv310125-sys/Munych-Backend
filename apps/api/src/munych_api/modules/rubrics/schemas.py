from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class CriterionIn(BaseModel):
    id: UUID | None = Field(
        default=None, description="Id de un criterio existente; vacío para crear uno nuevo"
    )
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    weight: Decimal = Field(gt=0, max_digits=5, decimal_places=2)
    level_descriptors: dict[str, str] = Field(
        default_factory=dict, description='Descriptor por nivel, p. ej. {"1": "Inicial"}'
    )


class RubricIn(BaseModel):
    """Rúbrica completa. El orden de `criteria` define su posición."""

    name: str = Field(min_length=1, max_length=200)
    scale_min: int = Field(ge=0, le=100)
    scale_max: int = Field(ge=1, le=100)
    criteria: list[CriterionIn] = Field(min_length=1, max_length=30)


class CriterionOut(BaseModel):
    id: UUID
    name: str
    description: str | None
    weight: float
    position: int
    level_descriptors: dict[str, str]


class RubricOut(BaseModel):
    id: UUID
    event_id: UUID
    name: str
    scale_min: int
    scale_max: int
    criteria: list[CriterionOut]
