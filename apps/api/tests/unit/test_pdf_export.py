"""Acta de resultados en PDF (2026-11-07), según la muestra oficial de MUNYCH."""

import re
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from reportlab import rl_config

from munych_api.modules.results.application.ports import (
    CommitteeResults,
    ExportData,
    ExportOptions,
)
from munych_api.modules.results.domain.models import (
    Award,
    CommitteeInfo,
    DelegateScore,
    DelegationInfo,
    NameFormat,
    RankingEntry,
)
from munych_api.modules.results.infrastructure.pdf_exporter import (
    PdfExporter,
    country_name,
    date_range,
    generated_text,
    score_text,
)


@pytest.fixture(autouse=True)
def uncompressed() -> Iterator[None]:
    """Sin compresión, el texto del PDF se puede buscar en los bytes."""
    previous = rl_config.pageCompression
    rl_config.pageCompression = 0
    yield
    rl_config.pageCompression = previous


def entry(
    position: int,
    code: str | None,
    name: str,
    score: str | None,
    *,
    tied: bool = False,
    character: str | None = None,
) -> RankingEntry:
    return RankingEntry(
        position=position,
        tied=tied,
        delegation=DelegationInfo(uuid.uuid4(), code, character, "Colegio Loyola", ()),
        delegates=(DelegateScore(uuid.uuid4(), name, None),),
        score=None if score is None else Decimal(score),
        criteria_averages={},
    )


def data(
    *,
    name_format: NameFormat = "first_name_initial",
    options: ExportOptions | None = None,
    committees: int = 2,
) -> ExportData:
    results = []
    for i in range(committees):
        info = CommitteeInfo(
            uuid.uuid4(),
            uuid.uuid4(),
            f"c{i}",
            f"Comite {i}",
            f"C{i}",
            "general_assembly",
            {},
            True,
        )
        ranking = [
            entry(1, "BR", "Diego Hernandez Ruiz", "95.54"),
            entry(2, "AE", "Ana Lopez", "90.5", tied=True),
            entry(2, None, "Luis Perez", "90.5", tied=True, character="Ministro de Defensa"),
            entry(4, "PL", "Rosa Diaz", None),
        ]
        awards = [Award("best_delegate", ranking[0].delegation.id)] if i == 0 else []
        results.append(CommitteeResults(info, ranking, awards, "mun_regular"))
    return ExportData(
        event_name="SD-MUN 2026",
        venue="Colegio X, Santo Domingo",
        starts_on=date(2026, 11, 14),
        ends_on=date(2026, 11, 16),
        timezone="America/Santo_Domingo",
        generated_at=datetime(2026, 11, 16, 23, 42, tzinfo=UTC),
        committees=results,
        details=[],
        options=options or ExportOptions(),
        event_type="mun_regular",
        name_format=name_format,
    )


def pages(content: bytes) -> int:
    return len(re.findall(rb"/Type /Page\b", content))


def test_acta_is_a_pdf_with_a_cover_and_a_page_per_committee() -> None:
    content = PdfExporter().export(data())
    assert content.startswith(b"%PDF-")
    assert pages(content) == 3
    for text in (
        b"SD-MUN 2026",
        b"Resumen de premiaci",
        b"Diego H.",
        b"95.54",
        b"Ministro de Defensa",
    ):
        assert text in content
    assert b"Hernandez" not in content  # nombre e inicial: hay menores


def test_names_follow_the_publication_format() -> None:
    full = PdfExporter().export(data(name_format="full"))
    assert b"Hernandez" in full
    hidden = PdfExporter().export(data(name_format="hidden"))
    assert b"Diego" not in hidden


def test_scores_can_be_left_out() -> None:
    content = PdfExporter().export(data(options=ExportOptions(include_scores=False)))
    assert b"95.54" not in content
    assert b"NOTA" not in content


def test_an_event_without_committees_still_renders() -> None:
    content = PdfExporter().export(data(committees=0))
    assert pages(content) == 1
    assert b"Todav" in content  # «Todavía no hay premios asignados.»


def test_user_text_is_escaped() -> None:
    d = data(committees=1)
    evil = entry(5, None, "<b>Ana</b> & Co", "50", character="<i>Rey</i> & Reina")
    d.committees[0].ranking.append(evil)
    content = PdfExporter().export(d)
    # El marcado del usuario sale como texto literal, no como formato (reportlab dibuja
    # los signos en trozos aparte: «(<) Tj (i) Tj (>) Tj (Rey)…»).
    assert b"(<) Tj (i) Tj (>) Tj (Rey)" in content
    assert b"(<) Tj (b) Tj (>) Tj (Ana)" in content


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (date(2026, 11, 14), date(2026, 11, 16), "14–16 nov 2026"),
        (date(2026, 10, 30), date(2026, 11, 2), "30 oct – 2 nov 2026"),
        (date(2026, 12, 30), date(2027, 1, 2), "30 dic 2026 – 2 ene 2027"),
        (date(2026, 11, 14), date(2026, 11, 14), "14 nov 2026"),
    ],
)
def test_date_range(start: date, end: date, expected: str) -> None:
    assert date_range(start, end) == expected


def test_generated_text_uses_the_event_timezone() -> None:
    moment = datetime(2026, 11, 16, 23, 42, tzinfo=UTC)
    assert generated_text(moment, "America/Santo_Domingo") == "16 nov 2026 · 19:42 (UTC-4)"
    assert generated_text(moment, "UTC") == "16 nov 2026 · 23:42 (UTC)"
    assert generated_text(moment, "Asia/Kolkata") == "17 nov 2026 · 05:12 (UTC+5:30)"


def test_country_names_and_scores() -> None:
    assert country_name("AE") == "Emiratos Árabes Unidos"
    assert country_name("sa") == "Arabia Saudí"
    assert country_name("XX") == "XX"
    assert score_text(Decimal("87.456")) == "87.46"
    assert score_text(None) == "—"
