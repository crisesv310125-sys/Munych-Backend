from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from munych_api.shared.kernel.catalog import EventStatus, EventType

Evaluates = Literal["delegations", "delegates", "position_papers", "press"]
"""A quién evalúa un tipo de staff."""
CountsAs = Literal["none", "staff", "chair"]
"""none: solo premios · staff: peso Staff del ranking · chair: peso Mesa Directiva."""
MemberRole = Literal["coordinator", "evaluator"]
AccessMode = Literal["link", "account"]
"""link: QR sin cuenta · account: cuenta con contraseña y panel del juez (Mesa Directiva)."""
AccessStatus = Literal["not_invited", "invited", "active", "expired"]
AwardScope = Literal["event", "per_committee"]
StaffTypeStatus = Literal[
    "not_configured", "invalid_rubric", "not_started", "in_progress", "complete"
]
RubricTemplate = Literal["press", "position_papers", "oratory", "protocol", "blank"]

Name = Annotated[str, Field(min_length=1, max_length=80)]
ShortText = Annotated[str, Field(max_length=300)]


def _strip(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


# ---------------------------------------------------------------- rúbrica


class CriterionIn(BaseModel):
    id: Annotated[str, Field(min_length=1, max_length=40)] | None = Field(
        default=None, description="Id de un criterio existente; null para uno nuevo"
    )
    name: Name
    description: ShortText | None = None
    weight: Annotated[Decimal, Field(ge=0, le=50, max_digits=5, decimal_places=2)]


class CriterionOut(BaseModel):
    id: str
    name: str
    description: str | None
    weight: float


class RubricIn(BaseModel):
    """Rúbrica completa del tipo (reemplaza la anterior). Pesos de 0 a 50 % que suman 100."""

    scale_min: Annotated[Decimal, Field(ge=0, le=1000)] = Decimal(0)
    scale_max: Annotated[Decimal, Field(gt=0, le=1000)] = Decimal(10)
    scale_step: Annotated[Decimal, Field(gt=0, le=100)] = Decimal("0.5")
    criteria: list[CriterionIn] = Field(min_length=1, max_length=20)


class RubricOut(BaseModel):
    scale_min: float
    scale_max: float
    scale_step: float
    criteria: list[CriterionOut]
    weight_sum: float
    valid: bool = Field(description="Suma 100 %, al menos un criterio y pesos de 0 a 50 %")


# ---------------------------------------------------------------- premios


class AwardIn(BaseModel):
    name: Name
    winners: Annotated[int, Field(ge=1, le=20)] = 1
    scope: AwardScope = "event"
    tiebreak_criterion_id: str | None = None


class AwardPatch(BaseModel):
    name: Name | None = None
    winners: Annotated[int, Field(ge=1, le=20)] | None = None
    scope: AwardScope | None = None
    tiebreak_criterion_id: str | None = None
    archived: bool | None = Field(default=None, description="true: quita el premio (no se borra)")


class AwardSlotOut(BaseModel):
    committee_id: UUID | None
    committee_acronym: str | None
    position: int
    candidate_id: UUID | None
    candidate_label: str | None
    candidate_score: float | None
    suggested_candidate_id: UUID | None = Field(description="Siguiente en el ranking sin premio")
    suggested_label: str | None
    suggested_score: float | None
    override_reason: str | None
    assigned_at: datetime | None


class AwardOut(BaseModel):
    id: UUID
    name: str
    winners: int
    scope: AwardScope
    tiebreak_criterion_id: str | None
    slots_total: int
    slots_assigned: int
    slots: list[AwardSlotOut] = Field(default_factory=list)


class AssignAwardIn(BaseModel):
    event_id: UUID = Field(description="Evento en el que se entrega el premio")
    committee_id: UUID | None = Field(default=None, description="Solo en premios por comité")
    position: Annotated[int, Field(ge=1, le=20)]
    candidate_id: UUID | None = Field(description="null: deja el lugar sin asignar")
    override_reason: Annotated[str, Field(max_length=500)] | None = None


class ConfirmAwardsIn(BaseModel):
    event_id: UUID = Field(description="Evento cuyos premios se confirman")
    confirmed: bool = Field(
        default=True, description="true congela los premios; false los vuelve a abrir"
    )


# ---------------------------------------------------------------- tipos de staff


class StaffTypeIn(BaseModel):
    """Nuevo tipo de staff (asistente: datos, evaluación y premios, rúbrica)."""

    name: Name
    code: Annotated[str, Field(min_length=1, max_length=3, pattern=r"^[A-Za-z0-9]+$")] | None = None
    color: Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$")] | None = None
    description: ShortText | None = None
    evaluates: Evaluates | None = None
    all_committees: bool = True
    committee_ids: list[UUID] = Field(default_factory=list, max_length=200)
    min_evaluators: Annotated[int, Field(ge=1, le=20)] = 2
    counts_as: CountsAs = "none"
    access: AccessMode = "link"
    template: RubricTemplate = "blank"
    awards: list[AwardIn] = Field(default_factory=list, max_length=20)

    @field_validator("description")
    @classmethod
    def _desc(cls, value: str | None) -> str | None:
        return _strip(value)


class StaffTypePatch(BaseModel):
    name: Name | None = None
    code: Annotated[str, Field(min_length=1, max_length=3, pattern=r"^[A-Za-z0-9]+$")] | None = None
    color: Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$")] | None = None
    description: ShortText | None = None
    evaluates: Evaluates | None = None
    all_committees: bool | None = None
    committee_ids: list[UUID] | None = Field(default=None, max_length=200)
    min_evaluators: Annotated[int, Field(ge=1, le=20)] | None = None
    counts_as: CountsAs | None = None
    access: AccessMode | None = None
    archived: bool | None = Field(default=None, description="true: oculta el tipo (no se borra)")


class StaffTypeSummaryOut(BaseModel):
    id: UUID
    name: str
    code: str
    color: str
    description: str | None
    evaluates: Evaluates | None
    all_committees: bool
    committee_ids: list[UUID]
    min_evaluators: int
    counts_as: CountsAs
    access: AccessMode
    criteria_count: int
    weight_sum: float
    rubric_valid: bool
    awards: list[AwardOut]
    members_count: int
    members_preview: list[str] = Field(description="Nombres de hasta 4 miembros (avatares)")
    candidates: int
    evaluations_done: int
    evaluations_expected: int
    progress: float | None = Field(description="0-100; null si no tiene miembros o candidatos")
    status: StaffTypeStatus
    awards_confirmed_at: datetime | None = Field(
        description="Premios confirmados en el evento de contexto"
    )


class EventRefOut(BaseModel):
    id: UUID
    name: str
    status: EventStatus
    event_type: EventType
    starts_on: date


class StaffOverviewOut(BaseModel):
    """Staff de la organización. Avance, candidatos y premios son del evento de contexto."""

    organization_name: str
    events: list[EventRefOut] = Field(
        description="Eventos de la organización (más reciente primero)"
    )
    event_id: UUID | None = Field(description="Evento de contexto (null: no hay eventos)")
    event_name: str | None
    event_type: EventType | None
    staff_weight: float | None = Field(description="Peso Staff del tipo de evento (null: no hay)")
    chair_weight: float | None = Field(description="Peso Mesa del tipo de evento (null: no hay)")
    types: list[StaffTypeSummaryOut]
    people: int = Field(description="Personas distintas en algún tipo de staff")
    people_active: int = Field(description="Personas que ya entraron con su enlace")
    awards_total: int
    awards_assigned: int
    progress: float | None = Field(description="Avance global (sin los tipos sin configurar)")


class MemberOut(BaseModel):
    id: UUID
    person_id: UUID
    full_name: str
    email: str | None
    title: str | None
    role: MemberRole
    committee_ids: list[UUID] = Field(description="Vacío = todos los comités del alcance")
    access: AccessStatus
    evaluated: int
    assigned: int = Field(description="Candidatos que le tocan")
    removed_at: datetime | None
    evaluations_count: bool
    other_types: list[str] = Field(description="Otros tipos de staff de la misma persona")


class CommitteeRefOut(BaseModel):
    id: UUID
    name: str
    acronym: str


class StaffTypeDetailOut(StaffTypeSummaryOut):
    event_id: UUID | None = Field(description="Evento de contexto del avance y los premios")
    rubric: RubricOut
    members: list[MemberOut]
    committees: list[CommitteeRefOut] = Field(description="Comités del evento de contexto")
    evaluations_exist: bool = Field(description="Hay evaluaciones (bloquea cambiar la escala)")


# ---------------------------------------------------------------- personas y miembros


class PersonIn(BaseModel):
    full_name: Annotated[str, Field(min_length=1, max_length=120)]
    email: Annotated[str, Field(max_length=200, pattern=r"^[^@\s]+@[^@\s]+$")] | None = None
    title: Annotated[str, Field(max_length=160)] | None = None

    @field_validator("full_name")
    @classmethod
    def _name(cls, value: str) -> str:
        return value.strip()

    @field_validator("email", "title")
    @classmethod
    def _opt(cls, value: str | None) -> str | None:
        return _strip(value)


class PersonPatch(BaseModel):
    full_name: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    email: Annotated[str, Field(max_length=200, pattern=r"^[^@\s]+@[^@\s]+$")] | None = None
    title: Annotated[str, Field(max_length=160)] | None = None


class PersonOut(BaseModel):
    id: UUID | None = Field(description="null: juez de la organización que aún no está en el staff")
    full_name: str
    email: str | None
    title: str | None
    access: AccessStatus
    types: list[str] = Field(description="Tipos de staff a los que pertenece")
    source: Literal["staff", "judge"]


class MemberIn(BaseModel):
    """Añade una persona al tipo: una que ya existe (`person_id`) o una nueva (`person`)."""

    person_id: UUID | None = None
    person: PersonIn | None = None
    role: MemberRole = "evaluator"
    committee_ids: list[UUID] = Field(default_factory=list, max_length=200)


class MemberPatch(BaseModel):
    role: MemberRole | None = None
    committee_ids: list[UUID] | None = Field(default=None, max_length=200)
    evaluations_count: bool | None = Field(
        default=None, description="Para exmiembros: si sus evaluaciones siguen contando"
    )
    restore: bool | None = Field(default=None, description="true: vuelve a activar al exmiembro")


class AccessLinkIn(BaseModel):
    link_base: Annotated[str, Field(min_length=10, max_length=300)] = Field(
        description="Prefijo del enlace; el token se añade al final. "
        "Ej.: https://panel.grandinternational.mx/#/staff/evaluar/"
    )

    @field_validator("link_base")
    @classmethod
    def _https(cls, value: str) -> str:
        local = value.startswith(("http://localhost", "http://127.0.0.1"))
        if not (value.startswith("https://") or local):
            raise ValueError("link_base debe empezar con https://")
        return value


class AccessLinkOut(BaseModel):
    """Enlace personal recién generado. El token **solo** se devuelve aquí, una vez."""

    person_id: UUID
    full_name: str
    email: str | None
    token: str
    url: str
    expires_at: datetime


# ---------------------------------------------------------------- invitar (por evento)


class StaffInviteIn(BaseModel):
    """Invitación desde la pantalla de jueces del evento: el rol se elige desde el inicio.

    - `role = "judge"`: juez (solo si el tipo de evento tiene jueces). Correo para crear
      contraseña.
    - `role = "staff"` con un tipo de acceso `account` (Mesa Directiva): correo para crear
      contraseña y rol de mesa en los comités elegidos (al menos uno).
    - `role = "staff"` con un tipo de acceso `link`: correo con su QR de acceso personal.
    """

    full_name: Annotated[str, Field(min_length=1, max_length=120)]
    email: Annotated[str, Field(max_length=200, pattern=r"^[^@\s]+@[^@\s]+$")]
    role: Literal["judge", "staff"]
    staff_type_id: UUID | None = None
    committee_ids: list[UUID] = Field(default_factory=list, max_length=50)
    member_role: MemberRole = "evaluator"
    title: Annotated[str, Field(max_length=160)] | None = None

    @field_validator("full_name")
    @classmethod
    def _trim(cls, value: str) -> str:
        return value.strip()

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        return value.strip().lower()


class StaffInviteOut(BaseModel):
    kind: Literal["judge", "account", "link"]
    """judge/account: se envió la invitación con contraseña; link: se envió el QR."""
    email: str
    full_name: str
    staff_type: str | None
    emailed: bool
    url: str | None = Field(
        default=None, description="Enlace personal (solo `link`); solo se devuelve aquí"
    )


class EventStaffMemberOut(BaseModel):
    """Una persona del staff en el evento (pantalla de jueces del evento)."""

    member_id: UUID
    person_id: UUID
    full_name: str
    email: str | None
    title: str | None
    staff_type_id: UUID
    staff_type: str
    code: str
    color: str
    access_mode: AccessMode
    role: MemberRole
    committee_ids: list[UUID]
    access: AccessStatus


# ---------------------------------------------------------------- ranking


class RankingRowOut(BaseModel):
    candidate_id: UUID
    label: str
    sublabel: str | None
    committee_id: UUID
    committee_acronym: str
    score: float | None = Field(description="0-100, promedio de evaluaciones completas")
    evaluations: int
    eligible: bool = Field(description="Tiene evaluaciones ≥ mínimo")
    position: int | None
    tied: bool
    awards: list[str] = Field(description="Premios asignados a este candidato")


class RankingOut(BaseModel):
    staff_type_id: UUID
    event_id: UUID | None
    committee_id: UUID | None
    min_evaluators: int
    rows: list[RankingRowOut]
    awards: list[AwardOut]
    awards_confirmed_at: datetime | None


# ---------------------------------------------------------------- vista del miembro (enlace)


class StaffCandidateOut(BaseModel):
    candidate_id: UUID
    label: str
    sublabel: str | None
    committee_acronym: str
    values: dict[str, float]
    comment: str | None
    complete: bool
    updated_at: datetime | None


class StaffAssignmentOut(BaseModel):
    """Un tipo de staff de la persona en un evento abierto de la organización."""

    member_id: UUID
    event_id: UUID
    event_name: str
    staff_type_id: UUID
    name: str
    code: str
    color: str
    role: MemberRole
    evaluates: Evaluates | None
    open: bool = Field(description="Si se puede evaluar ahora")
    closed_reason: str | None
    scale_min: float
    scale_max: float
    scale_step: float
    criteria: list[CriterionOut]
    candidates: list[StaffCandidateOut]


class StaffMeOut(BaseModel):
    full_name: str
    title: str | None
    organization_name: str
    assignments: list[StaffAssignmentOut] = Field(
        description="Por tipo de staff y evento no cerrado de la organización"
    )


class StaffEvaluationIn(BaseModel):
    """Autoguardado: valores parciales o completos de una evaluación."""

    member_id: UUID
    event_id: UUID
    candidate_id: UUID
    values: dict[Annotated[str, Field(max_length=40)], Decimal] = Field(max_length=20)
    comment: Annotated[str, Field(max_length=2000)] | None = None
    client_updated_at: datetime | None = None


class StaffEvaluationOut(BaseModel):
    candidate_id: UUID
    values: dict[str, float]
    comment: str | None
    complete: bool
    updated_at: datetime | None
