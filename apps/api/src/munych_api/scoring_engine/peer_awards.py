"""Nota del voto entre pares por premios (handoff «Votación de delegados», 2026-11-06).

Cada delegado vota una vez por comité y elige tres delegaciones distintas:

    Mejor delegado 3 puntos · Delegado distinguido 2 · Mención honorífica 1

Nota de una delegación (0-100) = puntos recibidos / (3 × votantes) × 100, donde
«votantes» son los delegados del comité que enviaron su boleta. Así la nota no
depende de cuántas delegaciones haya y 100 significa «todos la eligieron como
mejor delegado». Sin votantes, la nota es `None` (el rol no cuenta y su peso se
reparte entre los demás, como cualquier rol sin votos).
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal

AWARD_POINTS: dict[str, int] = {
    "best_delegate": 3,
    "outstanding_delegate": 2,
    "honorable_mention": 1,
}
"""Puntos por premio. El orden es el de la boleta."""

MAX_POINTS = max(AWARD_POINTS.values())


@dataclass(frozen=True, slots=True)
class AwardVote:
    """Un premio que un delegado (`voter_id`) da a una delegación."""

    voter_id: str
    delegation_id: str
    award_type: str


def peer_award_scores(
    votes: Iterable[AwardVote], delegation_ids: Sequence[str]
) -> dict[str, Decimal | None]:
    """Nota 0-100 de cada delegación según los premios recibidos."""
    votes = list(votes)
    voters = {v.voter_id for v in votes}
    if not voters:
        return dict.fromkeys(delegation_ids)
    points = dict.fromkeys(delegation_ids, 0)
    for v in votes:
        if v.delegation_id in points:
            points[v.delegation_id] += AWARD_POINTS[v.award_type]
    max_total = Decimal(MAX_POINTS * len(voters))
    return {d: Decimal(p) * 100 / max_total for d, p in points.items()}
