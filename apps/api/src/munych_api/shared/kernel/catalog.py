"""Catálogos y valores por defecto de negocio (secciones 5, 6.1 y 6.4)."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

Brand = Literal["munych", "grand_international"]
EventStatus = Literal["draft", "active", "closed"]
EventType = Literal["judges_only", "mun_regular", "national_championship"]
VoterRole = Literal["judge", "chair", "staff", "delegate"]
"""Grupo que vota. `chair` es la Mesa Directiva (presidente, moderador...)."""

JudgeRole = Literal["chair", "moderator", "judge", "staff"]
"""Rol de una cuenta (juez, mesa o staff) dentro de un comité (`committee_judges.role`)."""

VOTER_ROLE_LABELS: dict[VoterRole, str] = {
    "judge": "Jueces",
    "chair": "Mesa Directiva",
    "staff": "Staff",
    "delegate": "Delegados",
}


@dataclass(frozen=True, slots=True)
class EventTypeConfig:
    """Qué roles votan en un tipo de evento y cuánto pesa cada uno (suman 100).

    Un tipo nuevo se añade aquí (y en el CHECK de `app.events.event_type`), sin
    programar un flujo aparte. El resultado de una delegación es la suma ponderada
    del promedio de cada rol (spec del 2026-11-05).
    """

    label: str
    voter_weights: dict[VoterRole, Decimal]

    @property
    def voter_roles(self) -> tuple[VoterRole, ...]:
        return tuple(self.voter_weights)

    @property
    def splits_judges(self) -> bool:
        """Si la mesa cuenta como un grupo aparte de los jueces.

        En `judges_only` todas las cuentas asignadas al comité (mesa incluida)
        califican como un solo grupo, igual que antes de los tipos de evento.
        """
        return len(self.voter_weights) > 1

    def account_voter_role(self, committee_role: str | None) -> VoterRole | None:
        """Grupo en el que cuenta una cuenta según su rol en el comité.

        Devuelve `None` si ese grupo no vota en este tipo de evento.
        """
        if not self.splits_judges:
            role: VoterRole = "judge"
        elif committee_role in ("chair", "moderator"):
            role = "chair"
        elif committee_role == "staff":
            role = "staff"
        else:
            role = "judge"
        return role if role in self.voter_weights else None


DEFAULT_EVENT_TYPE: EventType = "judges_only"

# TODO(cliente): confirmar con Héctor que SD-MUN-2026 es un MUN regular.
EVENT_TYPES: dict[EventType, EventTypeConfig] = {
    "judges_only": EventTypeConfig(
        label="Solo jueces",
        voter_weights={"judge": Decimal(100)},
    ),
    "mun_regular": EventTypeConfig(
        label="MUN regular (mesa, delegados y staff)",
        voter_weights={"chair": Decimal(30), "delegate": Decimal(50), "staff": Decimal(20)},
    ),
    "national_championship": EventTypeConfig(
        label="Campeonato Nacional MUNer (jueces, mesa, delegados y staff)",
        voter_weights={
            "judge": Decimal(50),
            "chair": Decimal(15),
            "delegate": Decimal(25),
            "staff": Decimal(10),
        },
    ),
}
CommitteeType = Literal["general_assembly", "security_council", "crisis", "specialized"]
DelegationMode = Literal["single", "double"]
SessionStatus = Literal["open", "closed"]
AwardType = Literal[
    "best_delegate", "outstanding_delegate", "honorable_mention", "verbal_commendation"
]

AWARD_TYPES: tuple[AwardType, ...] = (
    "best_delegate",
    "outstanding_delegate",
    "honorable_mention",
    "verbal_commendation",
)

AWARD_LABELS: dict[AwardType, str] = {
    "best_delegate": "Mejor delegado",
    "outstanding_delegate": "Delegado destacado",
    "honorable_mention": "Mención honorífica",
    "verbal_commendation": "Mención verbal",
}

# TODO(cliente): confirmar premios automáticos (MVP: manuales; los cupos solo avisan).
DEFAULT_AWARD_QUOTAS: dict[CommitteeType, dict[AwardType, int]] = {
    "general_assembly": {
        "best_delegate": 1,
        "outstanding_delegate": 2,
        "honorable_mention": 2,
        "verbal_commendation": 3,
    },
    "security_council": {
        "best_delegate": 1,
        "outstanding_delegate": 1,
        "honorable_mention": 2,
        "verbal_commendation": 2,
    },
    "crisis": {
        "best_delegate": 1,
        "outstanding_delegate": 1,
        "honorable_mention": 1,
        "verbal_commendation": 2,
    },
    "specialized": {
        "best_delegate": 1,
        "outstanding_delegate": 1,
        "honorable_mention": 2,
        "verbal_commendation": 3,
    },
}

MAX_DELEGATES: dict[DelegationMode, int] = {"single": 1, "double": 2}

DEFAULT_RUBRIC_NAME = "Rúbrica por defecto"
DEFAULT_SCALE = (1, 4)
DEFAULT_LEVEL_DESCRIPTORS: dict[str, str] = {
    "1": "Inicial",
    "2": "En desarrollo",
    "3": "Competente",
    "4": "Excepcional",
}
# TODO(cliente): confirmar papel de posición (no se evalúa en el MVP).
DEFAULT_CRITERIA: tuple[tuple[str, Decimal], ...] = (
    ("Conocimiento del tema y posición del país", Decimal(20)),
    ("Oratoria (debate formal)", Decimal(20)),
    ("Negociación y liderazgo (debate informal)", Decimal(20)),
    ("Contribución a resoluciones", Decimal(15)),
    ("Diplomacia y conducta", Decimal(15)),
    ("Uso del reglamento", Decimal(10)),
)

EVENT_LOGOS_BUCKET = "event-logos"
LOGO_CONTENT_TYPES: dict[str, str] = {
    "image/png": "png",
    "image/svg+xml": "svg",
    "image/webp": "webp",
}
LOGO_MAX_BYTES = 2 * 1024 * 1024
