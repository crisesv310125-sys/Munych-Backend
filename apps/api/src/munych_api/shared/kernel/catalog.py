"""Catálogos y valores por defecto de negocio (secciones 5, 6.1 y 6.4)."""

from decimal import Decimal
from typing import Literal

Brand = Literal["munych", "grand_international"]
EventStatus = Literal["draft", "active", "closed"]
CommitteeType = Literal["general_assembly", "security_council", "crisis", "specialized"]
DelegationMode = Literal["single", "double"]
JudgeRole = Literal["chair", "moderator", "judge"]
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
