"""Privacidad de `build_public_view` (sección 9): hay menores de edad."""

import itertools
import json
import re
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest

from munych_api.modules.results.domain.models import (
    Award,
    CommitteeInfo,
    DelegateInfo,
    DelegateScore,
    DelegationInfo,
    EventInfo,
    IncompleteFlag,
    NameFormat,
    PublicationSettings,
    RankingEntry,
    SpecialAward,
)
from munych_api.modules.results.domain.public_view import build_public_view, format_name
from munych_api.modules.results.domain.snapshot import build_snapshot

PUBLISHED_AT = datetime(2026, 10, 11, 23, 0, tzinfo=UTC)
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
JUDGE_ID = uuid.uuid4()

ANA = DelegateInfo(uuid.uuid4(), "Ana Pérez López")
JOHN = DelegateInfo(uuid.uuid4(), "John Smith")
MARY = DelegateInfo(uuid.uuid4(), "Mary Jones")
MX = DelegationInfo(uuid.uuid4(), "MX", None, "Colegio Ejemplo", (ANA,))
US = DelegationInfo(uuid.uuid4(), "US", None, "Instituto Norte", (JOHN, MARY))
MINISTER = DelegationInfo(uuid.uuid4(), None, "Ministro de Defensa", "Colegio Sur", ())


def _entry(position: int, delegation: DelegationInfo, score: str) -> RankingEntry:
    return RankingEntry(
        position=position,
        tied=False,
        delegation=delegation,
        delegates=tuple(
            DelegateScore(d.id, d.full_name, Decimal(score)) for d in delegation.delegates
        ),
        score=Decimal(score),
        criteria_averages={uuid.uuid4(): Decimal("3.5")},
        incomplete_flags=(IncompleteFlag("incomplete", ANA.id, 1, JUDGE_ID),),
    )


def _snapshot() -> dict[str, Any]:
    event = EventInfo(
        id=uuid.uuid4(),
        slug="sd-mun-2026",
        name="SD-MUN 2026",
        brand="grand_international",
        logo_path="x/logo.png",
        venue="Santo Domingo",
        timezone="America/Santo_Domingo",
        starts_on=date(2026, 10, 9),
        ends_on=date(2026, 10, 11),
        status="closed",
    )
    committee = CommitteeInfo(
        id=uuid.uuid4(),
        event_id=event.id,
        slug="disec",
        name="Primera Comisión",
        acronym="DISEC",
        type="general_assembly",
        award_quotas={"best_delegate": 1},
        event_closed=True,
    )
    ranking = [_entry(1, MX, "87.456"), _entry(2, US, "80"), _entry(3, MINISTER, "10")]
    awards = [
        Award("outstanding_delegate", US.id, 1),
        Award("best_delegate", MX.id, 1),
    ]
    return build_snapshot(
        event,
        "https://cdn/logo.png",
        [(committee, ranking, awards)],
        PublicationSettings(),
        PUBLISHED_AT,
    )


def _view(**settings: Any) -> dict[str, Any]:
    return build_public_view(
        _snapshot(), PublicationSettings(**settings), version=3, published_at=PUBLISHED_AT
    )


# ---------------------------------------------------------------- formato de nombres


@pytest.mark.parametrize(
    ("name", "name_format", "expected"),
    [
        ("Ana Pérez López", "first_name_initial", "Ana P."),
        ("John Smith", "first_name_initial", "John S."),
        ("Juan de la Cruz", "first_name_initial", "Juan C."),
        ("Yuki", "first_name_initial", "Yuki"),
        ("  Ana   Pérez  ", "first_name_initial", "Ana P."),
        ("João silva", "first_name_initial", "João S."),
        ("Ana Pérez López", "full", "Ana Pérez López"),
        ("Ana Pérez López", "hidden", None),
    ],
)
def test_format_name(name: str, name_format: NameFormat, expected: str | None) -> None:
    assert format_name(name, name_format) == expected


# ---------------------------------------------------------------- forma del documento


def test_default_document_matches_contract() -> None:
    view = _view()
    assert view == {
        "event": {
            "slug": "sd-mun-2026",
            "name": "SD-MUN 2026",
            "brand": "grand_international",
            "logo_url": "https://cdn/logo.png",
            "venue": "Santo Domingo",
            "starts_on": "2026-10-09",
            "ends_on": "2026-10-11",
            "timezone": "America/Santo_Domingo",
        },
        "settings": {
            "name_format": "first_name_initial",
            "show_institution": True,
            "show_ranking": False,
            "show_scores": False,
            "indexable": False,
        },
        "committees": [
            {
                "slug": "disec",
                "name": "Primera Comisión",
                "acronym": "DISEC",
                "type": "general_assembly",
                "awards": [
                    {
                        "award_type": "best_delegate",
                        "position": 1,
                        "delegation": {
                            "country_code": "MX",
                            "character_name": None,
                            "institution": "Colegio Ejemplo",
                        },
                        "delegates": ["Ana P."],
                    },
                    {
                        "award_type": "outstanding_delegate",
                        "position": 1,
                        "delegation": {
                            "country_code": "US",
                            "character_name": None,
                            "institution": "Instituto Norte",
                        },
                        "delegates": ["John S.", "Mary J."],
                    },
                ],
                "ranking": None,
            }
        ],
        "general_ranking": None,
        "special_awards": [],
        "published_at": "2026-10-11T23:00:00Z",
        "version": 3,
    }


def test_ranking_with_scores_is_rounded() -> None:
    ranking = _view(show_ranking=True, show_scores=True)["committees"][0]["ranking"]
    assert [(r["position"], r["score"]) for r in ranking] == [(1, 87.46), (2, 80.0), (3, 10.0)]
    assert ranking[2]["delegation"]["character_name"] == "Ministro de Defensa"
    assert ranking[2]["delegates"] == []


def test_general_ranking_mixes_committees_by_score() -> None:
    snapshot = _snapshot()
    second = dict(snapshot["committees"][0], slug="cs", name="Consejo de Seguridad", acronym="CS")
    second["ranking"] = [
        dict(snapshot["committees"][0]["ranking"][1], score=87.46),  # empata con MX
        dict(snapshot["committees"][0]["ranking"][2], score=None),  # sin nota: no aparece
    ]
    snapshot["committees"].append(second)
    view = build_public_view(
        snapshot,
        PublicationSettings(show_ranking=True, show_scores=True),
        version=1,
        published_at=PUBLISHED_AT,
    )
    rows = [
        (
            r["position"],
            r["committee"]["acronym"],
            r["delegation"]["country_code"] or "-",
            r["score"],
        )
        for r in view["general_ranking"]
    ]
    assert rows == [
        (1, "CS", "US", 87.46),
        (1, "DISEC", "MX", 87.46),
        (3, "DISEC", "US", 80.0),
        (4, "DISEC", "-", 10.0),
    ]


# ---------------------------------------------------------------- privacidad (combinaciones)

COMBINATIONS = [
    {
        "name_format": name_format,
        "show_institution": show_institution,
        "show_ranking": show_ranking,
        "show_scores": show_scores,
        "indexable": indexable,
    }
    for name_format, show_institution, show_ranking, show_scores, indexable in itertools.product(
        ("full", "first_name_initial", "hidden"), *[(True, False)] * 4
    )
]


def _ids(settings: dict[str, Any]) -> str:
    return "-".join(f"{k}={v}" for k, v in settings.items())


@pytest.mark.parametrize("settings", COMBINATIONS, ids=[_ids(s) for s in COMBINATIONS])
def test_privacy_for_every_combination(settings: dict[str, Any]) -> None:
    view = _view(**settings)
    text = json.dumps(view, ensure_ascii=False)
    committee = view["committees"][0]

    # Nunca: UUID (de personas, delegaciones o del evento), jueces, comentarios ni marcas.
    assert not UUID_RE.search(text)
    assert str(JUDGE_ID) not in text
    for forbidden in ("judge", "comment", "incomplete", "criteria_averages", "full_name"):
        assert forbidden not in text

    delegates = [n for a in committee["awards"] for n in a["delegates"]]
    if committee["ranking"]:
        delegates += [n for r in committee["ranking"] for n in r["delegates"]]
    if settings["name_format"] == "hidden":
        assert delegates == []
    elif settings["name_format"] == "first_name_initial":
        assert "Pérez" not in text
        assert "López" not in text
        assert "Smith" not in text
        assert "Ana P." in delegates
    else:
        assert "Ana Pérez López" in delegates

    institutions = [a["delegation"]["institution"] for a in committee["awards"]]
    if settings["show_institution"]:
        assert "Colegio Ejemplo" in institutions
    else:
        assert set(institutions) == {None}
        assert "Colegio" not in text
        assert "Instituto" not in text

    if not settings["show_ranking"]:
        assert committee["ranking"] is None
    else:
        scores = [r["score"] for r in committee["ranking"]]
        if settings["show_scores"]:
            assert scores == [87.46, 80.0, 10.0]
        else:
            assert set(scores) == {None}
    if not settings["show_scores"]:
        assert "87.46" not in text

    assert view["settings"]["indexable"] is settings["indexable"]


@pytest.mark.parametrize("settings", COMBINATIONS, ids=[_ids(s) for s in COMBINATIONS])
def test_general_ranking_follows_the_same_privacy(settings: dict[str, Any]) -> None:
    view = _view(**settings)
    general = view["general_ranking"]
    if not settings["show_ranking"]:
        assert general is None
        return
    assert {r["score"] is None for r in general} == {not settings["show_scores"]}
    names = [n for r in general for n in r["delegates"]]
    if settings["name_format"] == "hidden":
        assert names == []
    if not settings["show_institution"]:
        assert {r["delegation"]["institution"] for r in general} == {None}


def test_settings_from_stored_json_uses_safe_defaults() -> None:
    assert PublicationSettings.from_dict(None) == PublicationSettings()
    parsed = PublicationSettings.from_dict(
        {"name_format": "otro", "show_scores": "sí", "show_ranking": True}
    )
    assert parsed == PublicationSettings(show_ranking=True)


# ---------------------------------------------------------------- premios especiales (staff)

SPECIAL = SpecialAward(
    staff_type="Prensa",
    award="Mejor periodista",
    position=1,
    committee_acronym="CP",
    country_code=None,
    character_name="The MUNYCH Times",
    delegates=("Sofía Méndez Ruiz",),
    institution="Colegio Ejemplo",
    score=Decimal("92.456"),
)


def test_special_awards_follow_the_whitelist() -> None:
    default = build_public_view(
        _snapshot(),
        PublicationSettings(),
        version=1,
        published_at=PUBLISHED_AT,
        special_awards=[SPECIAL],
    )["special_awards"]
    assert default == [
        {
            "staff": "Prensa",
            "award": "Mejor periodista",
            "position": 1,
            "winners": 1,
            "committee_acronym": "CP",
            "delegation": {
                "country_code": None,
                "character_name": "The MUNYCH Times",
                "institution": "Colegio Ejemplo",
            },
            "delegates": ["Sofía M."],
            "score": None,
        }
    ]
    strict = build_public_view(
        _snapshot(),
        PublicationSettings(name_format="hidden", show_institution=False, show_scores=True),
        version=1,
        published_at=PUBLISHED_AT,
        special_awards=[SPECIAL],
    )["special_awards"][0]
    assert strict["delegates"] == []
    assert strict["delegation"]["institution"] is None
    assert strict["score"] == 92.46
