"""Acta de resultados en PDF (2026-11-07).

Reproduce la muestra oficial que entregó MUNYCH («Acta de resultados - muestra oficial»):
una portada con los datos del evento y el resumen de premiación de todos los comités, y
luego una sección por comité con sus premios y su ranking. Pie en todas las páginas.

Se genera con reportlab (Python puro, sin dependencias del sistema). Usa las fuentes
estándar del PDF (Times, Helvetica y Courier) para no tener que incrustar archivos; la
muestra usa Playfair Display, Inter y una monoespaciada, y se parece bastante.

Las casillas de la pantalla Exportar (`ExportOptions`) añaden, por comité:
- «Desglose por criterio»: la media de cada criterio de la rúbrica por delegación, y las
  calificaciones por delegado, sesión y juez.
- «Nombre del juez»: el nombre real en esas calificaciones (si no, «Juez 1», «Juez 2»…).
- «Comentarios de los jueces»: sus comentarios junto a cada calificación.

Privacidad: los nombres de los delegados siguen el formato de la publicación (por defecto,
nombre e inicial del apellido: hay menores). Con nombres de jueces o comentarios, la portada
avisa de que es un documento interno.
"""

import io
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from babel import Locale
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    CondPageBreak,
    Flowable,
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from munych_api.modules.results.application.ports import (
    CommitteeResults,
    ExportData,
    ScoreDetail,
)
from munych_api.modules.results.domain.awards import sort_awards
from munych_api.modules.results.domain.models import Award, NameFormat, RankingEntry, RubricInfo
from munych_api.modules.results.domain.public_view import format_name
from munych_api.scoring_engine import present
from munych_api.shared.kernel.catalog import (
    AWARD_LABELS,
    EVENT_TYPES,
    VOTER_ROLE_LABELS,
    AwardType,
    EventType,
)

PDF_MEDIA_TYPE = "application/pdf"

# ---------------------------------------------------------------- diseño (muestra oficial)

NAVY = colors.HexColor("#14304F")
INK = colors.HexColor("#1F2A37")
MUTED = colors.HexColor("#5F6F82")
FAINT = colors.HexColor("#8A97A6")
BORDER = colors.HexColor("#E2E7ED")
SOFT_BG = colors.HexColor("#F3F5F8")
CHIP_BG = colors.HexColor("#EDF0F4")
FIRST_ROW = colors.HexColor("#FCFAF1")
GOLD = colors.HexColor("#C9A227")
TIE_BG = colors.HexColor("#FBF1CF")
WARN_BG = colors.HexColor("#FBF3DE")
# Los mismos colores como texto, para el marcado de Paragraph.
NAVY_HEX, INK_HEX, MUTED_HEX, GOLD_HEX = "#14304F", "#1F2A37", "#5F6F82", "#C9A227"
CHIP_BG_HEX, TIE_BG_HEX = "#EDF0F4", "#FBF1CF"

AWARD_DOT: dict[AwardType, str] = {
    "best_delegate": "#C9A227",
    "outstanding_delegate": "#9AA4AF",
    "honorable_mention": "#B8784A",
    "verbal_commendation": "#C8CED6",
}

BRANDS = {"munych": "MUNYCH Association", "grand_international": "GRAND International"}
COMMITTEE_TYPES = {
    "general_assembly": "Asamblea General",
    "security_council": "Consejo de Seguridad",
    "crisis": "Crisis",
    "specialized": "Especializado",
}
NAME_NOTES: dict[NameFormat, str] = {
    "full": "nombres completos",
    "first_name_initial": "nombre e inicial del apellido (protección de menores)",
    "hidden": "nombres de delegados ocultos (protección de menores)",
}
MONTHS = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")

SERIF, SERIF_BOLD = "Times-Roman", "Times-Bold"
SANS, SANS_BOLD = "Helvetica", "Helvetica-Bold"
MONO = "Courier-Bold"

PAGE_W, PAGE_H = LETTER
MARGIN_X = 0.6 * inch
CONTENT_W = PAGE_W - 2 * MARGIN_X


def _style(name: str, **kw: object) -> ParagraphStyle:
    base: dict[str, object] = {"fontName": SANS, "fontSize": 8.5, "leading": 11, "textColor": INK}
    base.update(kw)
    return ParagraphStyle(name, **base)


S_BODY = _style("body")
S_MUTED = _style("muted", textColor=MUTED, fontSize=8)
S_HEAD = _style("head", fontSize=6.5, leading=8, textColor=MUTED)
S_HEAD_R = _style("head_r", fontSize=6.5, leading=8, textColor=MUTED, alignment=TA_RIGHT)
S_TITLE = _style("title", fontName=SERIF_BOLD, fontSize=30, leading=34, textColor=NAVY)
S_H2 = _style("h2", fontName=SERIF_BOLD, fontSize=15, leading=18, textColor=NAVY)
S_H1C = _style("h1c", fontName=SERIF_BOLD, fontSize=22, leading=26, textColor=NAVY)
S_COMMITTEE = _style("committee", fontName=SERIF_BOLD, fontSize=9.5, leading=11.5, textColor=NAVY)
S_SCORE = _style("score", fontName=SERIF_BOLD, fontSize=10.5, alignment=TA_RIGHT, textColor=NAVY)
S_NAME = _style("name", fontName=SANS_BOLD, fontSize=8.5)
S_LABEL = _style("label", fontSize=6.5, leading=8, textColor=MUTED)
S_VALUE = _style("value", fontSize=9, leading=11)
S_RIGHT_MUTED = _style("right_muted", textColor=MUTED, fontSize=8, alignment=TA_RIGHT)
S_ACRONYM = _style("acronym", fontName=MONO, fontSize=6.5, textColor=MUTED)
S_POS = _style("rpos", fontName=MONO, fontSize=8.5, textColor=NAVY, alignment=1)
S_WARNING = _style("warning", fontSize=8, leading=11, textColor=colors.HexColor("#6B500C"))
S_SMALL = _style("small", fontSize=7.5, leading=9.5)
S_SMALL_MUTED = _style("small_muted", fontSize=7, leading=9, textColor=MUTED)

NO_AWARDS_TEXT = "Sin premios asignados en este comité. El ranking se publica igualmente."


def spaced(text: str) -> str:
    """Rótulo con letras espaciadas, como los de la muestra («A C T A   D E …»).

    Entre palabras van espacios duros: Paragraph colapsa los espacios normales.
    """
    return "&nbsp;&nbsp;&nbsp;".join(" ".join(escape(word)) for word in text.upper().split())


def p(text: str, style: ParagraphStyle = S_BODY) -> Paragraph:
    return Paragraph(text, style)


def e(value: object) -> str:
    """Escapa texto del usuario para el marcado de Paragraph."""
    return escape(str(value))


# ---------------------------------------------------------------- formato


_COUNTRIES = Locale("es").territories


def country_name(code: str) -> str:
    return str(_COUNTRIES.get(code.upper(), code))


def delegation_name(entry: RankingEntry) -> str:
    d = entry.delegation
    if d.character_name:
        return d.character_name
    return country_name(d.country_code) if d.country_code else "—"


def score_text(value: Decimal | None) -> str:
    rounded = present(value)
    return "—" if rounded is None else f"{rounded:.2f}"


def short_date(value: date) -> str:
    return f"{value.day} {MONTHS[value.month - 1]} {value.year}"


def date_range(start: date, end: date) -> str:
    if start == end:
        return short_date(start)
    if (start.year, start.month) == (end.year, end.month):
        return f"{start.day}–{end.day} {MONTHS[end.month - 1]} {end.year}"
    if start.year == end.year:
        return f"{start.day} {MONTHS[start.month - 1]} – {short_date(end)}"
    return f"{short_date(start)} – {short_date(end)}"


def generated_text(moment: datetime, timezone: str) -> str:
    local = moment.astimezone(ZoneInfo(timezone))
    offset = local.utcoffset()
    minutes = int(offset.total_seconds() // 60) if offset else 0
    sign = "-" if minutes < 0 else "+"
    hours, rest = divmod(abs(minutes), 60)
    utc = f"UTC{sign}{hours}" + (f":{rest:02d}" if rest else "") if minutes else "UTC"
    return f"{short_date(local.date())} · {local:%H:%M} ({utc})"


def short_event_type(event_type: EventType) -> str:
    return EVENT_TYPES[event_type].label.split(" (")[0]


def weights_text(event_type: EventType, *, lower: bool = False) -> list[tuple[str, int]]:
    return [
        (VOTER_ROLE_LABELS[role].lower() if lower else VOTER_ROLE_LABELS[role], int(weight))
        for role, weight in EVENT_TYPES[event_type].voter_weights.items()
    ]


def award_markup(award_type: AwardType, suffix: str = "") -> str:
    """Punto de color del premio (como en la muestra) + su nombre."""
    dot = f'<font name="{SANS}" size="10" color="{AWARD_DOT[award_type]}">•</font>'
    return f"{dot}&nbsp;{e(AWARD_LABELS[award_type])}{suffix}"


def delegation_markup(entry: RankingEntry, *, muted: bool = False) -> str:
    name = e(delegation_name(entry))
    color = MUTED.hexval()[2:] if muted else INK.hexval()[2:]
    text = f'<font name="{SANS_BOLD}" color="#{color}">{name}</font>'
    code = entry.delegation.country_code if not entry.delegation.character_name else None
    if code:
        chip = (
            f'<font name="{MONO}" size="6.5" color="{NAVY_HEX}" '
            f'backColor="{CHIP_BG_HEX}">&nbsp;{e(code.upper())}&nbsp;</font>'
        )
        return f"{chip}&nbsp;&nbsp;{text}"
    return text


def detail_delegation_markup(label: str) -> str:
    """Delegación del detalle de calificaciones: llega como código ISO o nombre de personaje."""
    if len(label) == 2 and label.isupper() and label in _COUNTRIES:
        chip = (
            f'<font name="{MONO}" size="6" color="{NAVY_HEX}" backColor="{CHIP_BG_HEX}">'
            f"&nbsp;{e(label)}&nbsp;</font>"
        )
        return f"{chip}&nbsp;{e(country_name(label))}"
    return e(label or "—")


# ---------------------------------------------------------------- piezas


class Monogram(Flowable):  # type: ignore[misc]  # reportlab no trae tipos
    """Logo de la muestra: círculo azul con borde dorado y la inicial de la marca."""

    def __init__(self, letter: str, size: float = 34) -> None:
        super().__init__()
        self.letter = letter
        self.width = self.height = size

    def draw(self) -> None:
        c = self.canv
        r = self.width / 2
        c.setFillColor(NAVY)
        c.setStrokeColor(GOLD)
        c.setLineWidth(1.4)
        c.circle(r, r, r - 0.7, stroke=1, fill=1)
        c.setFillColor(GOLD)
        c.setFont(SERIF_BOLD, self.width * 0.5)
        c.drawCentredString(r, r - self.width * 0.17, self.letter)


def data_table(
    header: Sequence[str],
    rows: list[list[object]],
    widths: Sequence[float],
    *,
    right: set[int],
    compact: bool = False,
) -> Table:
    head = [p(e(h), S_HEAD_R if i in right else S_HEAD) for i, h in enumerate(header)]
    table = Table([head, *rows], colWidths=list(widths), repeatRows=1)
    padding = 2.5 if compact else 5
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), padding),
                ("BOTTOMPADDING", (0, 0), (-1, -1), padding),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("LINEBELOW", (0, 0), (-1, 0), 0.8, BORDER),
                ("LINEBELOW", (0, 1), (-1, -1), 0.5, BORDER),
                ("TOPPADDING", (0, 0), (-1, 0), 3),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
            ]
        )
    )
    return table


def info_boxes(cells: list[tuple[str, str]], widths: Sequence[float]) -> Table:
    row = [[p(spaced(label), S_LABEL), p(e(value), S_VALUE)] for label, value in cells]
    table = Table([row], colWidths=list(widths), cornerRadii=[5, 5, 5, 5])
    table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.7, BORDER),
                ("LINEAFTER", (0, 0), (-2, -1), 0.7, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ]
        )
    )
    return table


def stats(items: list[tuple[int, str]], *, align_right: bool = False) -> Table:
    style = S_HEAD_R if align_right else S_HEAD
    number = _style(
        "stat_n", fontSize=7.5, textColor=MUTED, alignment=TA_RIGHT if align_right else 0
    )
    cells = [[p(str(n), number), p(spaced(label), style)] for n, label in items]
    # Ancho de cada rótulo: letras espaciadas a 6.5 pt (≈ 2 caracteres por letra) + aire.
    widths = [len(label) * 7.2 + 14 for _, label in items]
    table = Table([cells], colWidths=widths, hAlign="RIGHT" if align_right else "LEFT")
    table.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0 if align_right else 12),
                ("LEFTPADDING", (1, 0), (-1, -1), 12 if align_right else 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return table


def note_line(parts: list[tuple[str, str]]) -> Paragraph:
    text = "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;".join(
        f'<font name="{SANS_BOLD}" color="{INK_HEX}">{e(k)}</font> {e(v)}' for k, v in parts
    )
    return p(text, _style("note", fontSize=7, leading=10, textColor=MUTED))


# ---------------------------------------------------------------- exportador


class PdfExporter:
    media_type = PDF_MEDIA_TYPE
    extension = "pdf"

    def export(self, data: ExportData) -> bytes:
        buffer = io.BytesIO()
        brand = BRANDS.get(data.brand, data.brand)
        generated = generated_text(data.generated_at, data.timezone)
        footer_left = f"{data.event_name}"
        footer_note = NAME_NOTES[data.name_format]

        def footer(canvas: Canvas, _doc: object) -> None:
            canvas.saveState()
            y = 0.45 * inch
            canvas.setStrokeColor(BORDER)
            canvas.setLineWidth(0.6)
            canvas.line(MARGIN_X, y + 11, PAGE_W - MARGIN_X, y + 11)
            canvas.setFont(SANS_BOLD, 6.5)
            canvas.setFillColor(NAVY)
            canvas.drawString(MARGIN_X, y, footer_left)
            offset = canvas.stringWidth(footer_left, SANS_BOLD, 6.5)
            canvas.setFont(SANS, 6.5)
            canvas.setFillColor(MUTED)
            canvas.drawString(MARGIN_X + offset, y, f" · Acta de resultados · Generada {generated}")
            canvas.drawRightString(PAGE_W - MARGIN_X, y, f"{brand} · {footer_note}")
            canvas.restoreState()

        doc = SimpleDocTemplate(
            buffer,
            pagesize=LETTER,
            leftMargin=MARGIN_X,
            rightMargin=MARGIN_X,
            topMargin=0.55 * inch,
            bottomMargin=0.8 * inch,
            title=f"{data.event_name} · Acta de resultados",
            author=brand,
            subject="Acta de resultados",
        )
        story: list[Flowable] = []
        story += self._cover(data, brand)
        total = len(data.committees)
        for i, committee in enumerate(data.committees, start=1):
            story.append(PageBreak())
            story += self._committee(data, committee, i, total, last=i == total)
        doc.build(story, onFirstPage=footer, onLaterPages=footer)
        return buffer.getvalue()

    # ------------------------------------------------------------ portada

    def _cover(self, data: ExportData, brand: str) -> list[Flowable]:
        brand_block = Table(
            [
                [
                    Monogram(brand[:1]),
                    [
                        p(
                            e(brand),
                            _style(
                                "brand",
                                fontName=SERIF_BOLD,
                                fontSize=13,
                                leading=15,
                                textColor=NAVY,
                            ),
                        ),
                        p(spaced("Modelo de Naciones Unidas"), S_LABEL),
                    ],
                    [
                        p(
                            spaced("Acta de resultados"),
                            _style(
                                "acta",
                                fontName=SANS_BOLD,
                                fontSize=7,
                                leading=9,
                                textColor=NAVY,
                                alignment=TA_RIGHT,
                            ),
                        ),
                        p(f"Documento oficial · {e(data.event_name)}", S_RIGHT_MUTED),
                    ],
                ]
            ],
            colWidths=[42, CONTENT_W * 0.5, CONTENT_W * 0.5 - 42],
        )
        brand_block.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
        story: list[Flowable] = [
            brand_block,
            Spacer(1, 10),
            HRFlowable(width="100%", thickness=2.4, color=NAVY, spaceAfter=18),
            p(e(data.event_name), S_TITLE),
            Spacer(1, 10),
            *self._warning_box(data),
            info_boxes(
                [
                    ("Sede", data.venue or "—"),
                    ("Fechas", date_range(data.starts_on, data.ends_on)),
                    ("Zona horaria", data.timezone),
                    ("Generada", generated_text(data.generated_at, data.timezone)),
                ],
                [CONTENT_W * 0.3, CONTENT_W * 0.22, CONTENT_W * 0.22, CONTENT_W * 0.26],
            ),
            Spacer(1, 7),
        ]

        weights = "&nbsp;&nbsp;".join(
            f'{e(role)} <font name="{MONO}" color="{NAVY_HEX}">{w} %</font>'
            for role, w in weights_text(data.event_type)
        )
        event_type = Table(
            [
                [
                    p(
                        f'<font size="6.5" color="{MUTED_HEX}">{spaced("Tipo de evento")}</font>'
                        f'&nbsp;&nbsp;&nbsp;&nbsp;<font name="{SANS_BOLD}" color="{NAVY_HEX}">'
                        f"{e(short_event_type(data.event_type))}</font>&nbsp;&nbsp;&nbsp;{weights}",
                        _style("type", textColor=MUTED),
                    )
                ]
            ],
            colWidths=[CONTENT_W],
            cornerRadii=[5, 5, 5, 5],
        )
        event_type.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), SOFT_BG),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ]
            )
        )
        delegations = sum(len(c.ranking) for c in data.committees)
        awards = sum(len(self._awards(c)) for c in data.committees)
        story += [
            event_type,
            Spacer(1, 12),
            stats(
                [
                    (len(data.committees), "Comités"),
                    (delegations, "Delegaciones"),
                    (awards, "Premios asignados"),
                ]
            ),
            Spacer(1, 14),
        ]

        heading = Table(
            [
                [
                    p(
                        f'<font name="{MONO}" size="8" color="{GOLD_HEX}">01</font>&nbsp;&nbsp;'
                        "Resumen de premiación",
                        S_H2,
                    ),
                    p(
                        f"Todos los comités · {awards} {'premio' if awards == 1 else 'premios'}",
                        S_RIGHT_MUTED,
                    ),
                ]
            ],
            colWidths=[CONTENT_W * 0.6, CONTENT_W * 0.4],
        )
        heading.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
        story += [heading, Spacer(1, 4)]

        include_scores = data.options.include_scores
        rows: list[list[object]] = []
        group_starts: list[int] = []
        for committee in data.committees:
            entries = {entry.delegation.id: entry for entry in committee.ranking}
            committee_awards = [a for a in self._awards(committee) if a.delegation_id in entries]
            counts: dict[str, int] = {}
            for a in committee_awards:
                counts[a.award_type] = counts.get(a.award_type, 0) + 1
            for k, award in enumerate(committee_awards):
                entry = entries[award.delegation_id]
                if k == 0:
                    group_starts.append(len(rows) + 1)
                committee_cell: object = (
                    [
                        p(e(committee.committee.name), S_COMMITTEE),
                        p(f"{e(committee.committee.acronym)}", S_ACRONYM),
                    ]
                    if k == 0
                    else ""
                )
                row: list[object] = [
                    committee_cell,
                    p(award_markup(award.award_type)),
                    p(
                        str(award.position) if counts[award.award_type] > 1 else "",
                        _style("pos", fontName=SANS_BOLD, textColor=NAVY),
                    ),
                    p(delegation_markup(entry)),
                    p(e(self._names(entry, data.name_format, ", ") or "—")),
                    p(e(entry.delegation.institution or "—"), S_MUTED),
                ]
                if include_scores:
                    row.append(p(score_text(entry.score), S_SCORE))
                rows.append(row)

        if rows:
            header = ["COMITÉ", "PREMIO", "POS.", "DELEGACIÓN", "DELEGADOS", "INSTITUCIÓN"]
            widths = [82, 96, 26, 112, 92, 82]
            if include_scores:
                header.append("NOTA")
                widths.append(42)
            else:
                widths[3] += 42
            table = data_table(header, rows, widths, right={6})
            table.setStyle(
                TableStyle([("VALIGN", (0, start), (0, start), "TOP") for start in group_starts])
            )
            story.append(table)
        else:
            story.append(p("Todavía no hay premios asignados.", S_MUTED))

        notes = [("Pos.", "orden dentro del mismo premio cuando hay varios")]
        if include_scores:
            notes.append(("Nota", self._score_note(data.event_type)))
        # Las notas van juntas (si no caben, pasan enteras a la página siguiente).
        story += [
            Spacer(1, 12),
            KeepTogether(
                [
                    HRFlowable(width="100%", thickness=0.6, color=BORDER, spaceAfter=6),
                    note_line(notes),
                    Spacer(1, 3),
                    note_line(
                        [
                            ("Nombres", NAME_NOTES[data.name_format]),
                            ("Contenido", self._contents(data)),
                        ]
                    ),
                ]
            ),
        ]
        return story

    def _warning_box(self, data: ExportData) -> list[Flowable]:
        warning = self._internal_warning(data)
        if not warning:
            return []
        box = Table([[p(warning, S_WARNING)]], colWidths=[CONTENT_W], cornerRadii=[5] * 4)
        box.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), WARN_BG),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ]
            )
        )
        return [box, Spacer(1, 8)]

    @staticmethod
    def _contents(data: ExportData) -> str:
        opts = data.options
        parts = ["resumen de premiación", "ranking por comité"]
        if opts.include_details:
            parts.append("desglose por criterio")
        if opts.include_details or opts.include_comments or opts.include_judge_names:
            parts.append("calificaciones por sesión")
        return ", ".join(parts)

    @staticmethod
    def _internal_warning(data: ExportData) -> str:
        """Aviso cuando el acta trae datos privados de los jueces (casillas de Exportar)."""
        opts = data.options
        private = []
        if opts.include_judge_names:
            private.append("los nombres de los jueces")
        if opts.include_comments:
            private.append("los comentarios de los jueces")
        if not private:
            return ""
        return (
            f"<b>Documento interno.</b> Incluye {' y '.join(private)}. "
            "No lo publiques ni lo compartas con delegados o instituciones."
        )

    # ------------------------------------------------------------ comité

    def _committee(
        self, data: ExportData, committee: CommitteeResults, index: int, total: int, *, last: bool
    ) -> list[Flowable]:
        info = committee.committee
        ranking = committee.ranking
        scored = sum(1 for entry in ranking if entry.score is not None)
        awards = [
            a
            for a in self._awards(committee)
            if any(entry.delegation.id == a.delegation_id for entry in ranking)
        ]
        type_label = COMMITTEE_TYPES.get(info.type, info.type)
        type_chip = Table(
            [[p(e(type_label), _style("chip", fontSize=7, textColor=NAVY))]],
            colWidths=[stringWidth(type_label, SANS, 7) + 16],
            cornerRadii=[7, 7, 7, 7],
            hAlign="LEFT",
        )
        type_chip.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
                    ("BACKGROUND", (0, 0), (-1, -1), SOFT_BG),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ]
            )
        )
        header = Table(
            [
                [
                    [
                        p(
                            f'<font name="{MONO}" size="7.5" color="{GOLD_HEX}">'
                            f"COMITÉ {index} DE {total}</font>"
                        ),
                        Spacer(1, 3),
                        p(f"{e(info.name)} ({e(info.acronym)})", S_H1C),
                        Spacer(1, 3),
                        type_chip,
                    ],
                    stats(
                        [
                            (len(ranking), "Delegaciones"),
                            (scored, "Con nota"),
                            (len(awards), "Premios"),
                        ],
                        align_right=True,
                    ),
                ]
            ],
            colWidths=[CONTENT_W * 0.62, CONTENT_W * 0.38],
        )
        header.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (0, 0), "TOP"),
                    ("VALIGN", (1, 0), (1, 0), "BOTTOM"),
                    ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
        story: list[Flowable] = [
            header,
            Spacer(1, 8),
            HRFlowable(width="100%", thickness=2.4, color=NAVY, spaceAfter=10),
        ]

        entries = {entry.delegation.id: entry for entry in ranking}
        story.append(self._awards_line(awards, entries))

        double = any(len(entry.delegates) > 1 for entry in ranking)
        subtitle = ("Delegaciones dobles · " if double else "") + "ordenado por nota final"
        story += [
            Spacer(1, 16),
            p(
                f'Ranking&nbsp;&nbsp;&nbsp;<font name="{SANS}" size="7.5" color="{MUTED_HEX}">'
                f"{subtitle}</font>",
                _style("rk", fontName=SERIF_BOLD, fontSize=11, textColor=NAVY),
            ),
            Spacer(1, 3),
        ]

        include_scores = data.options.include_scores
        awards_by: dict[object, list[AwardType]] = {}
        for a in awards:
            awards_by.setdefault(a.delegation_id, []).append(a.award_type)
        tie = (
            f'<font name="{MONO}" size="6" color="#8A6A12" backColor="{TIE_BG_HEX}">'
            "&nbsp;SÍ&nbsp;</font>"
        )
        rows: list[list[object]] = []
        for entry in ranking:
            no_score = entry.score is None
            row: list[object] = [
                p(
                    "–" if no_score else str(entry.position),
                    _style("rpos", fontName=MONO, fontSize=8.5, textColor=NAVY, alignment=1),
                ),
                p(tie if entry.tied and not no_score else "", _style("tie", alignment=1)),
                p(delegation_markup(entry, muted=no_score)),
                p(self._names_markup(entry, data.name_format)),
                p(e(entry.delegation.institution or "—"), S_MUTED),
            ]
            if include_scores:
                row.append(p(score_text(entry.score), S_SCORE if not no_score else S_RIGHT_MUTED))
            row.append(
                p(
                    "<br/>".join(award_markup(t) for t in awards_by.get(entry.delegation.id, [])),
                    _style("aw", fontSize=8),
                )
            )
            rows.append(row)

        header_row = ["POS.", "EMP.", "DELEGACIÓN", "DELEGADOS", "INSTITUCIÓN"]
        widths = [32, 30, 118, 92, 96]
        if include_scores:
            header_row.append("NOTA")
            widths.append(44)
        header_row.append("PREMIOS")
        widths.append(CONTENT_W - sum(widths))
        if rows:
            table = data_table(header_row, rows, widths, right={5} if include_scores else set())
            if ranking and ranking[0].score is not None:
                table.setStyle(TableStyle([("BACKGROUND", (0, 1), (-1, 1), FIRST_ROW)]))
            story.append(table)
        else:
            story.append(p("Este comité no tiene delegaciones.", S_MUTED))

        opts = data.options
        rubric = committee.rubric
        if opts.include_details and rubric is not None and rubric.criteria and ranking:
            story += self._criteria_breakdown(committee, rubric, include_scores=include_scores)
        details = [d for d in data.details if self._belongs(d, committee)]
        if details and (opts.include_details or opts.include_comments or opts.include_judge_names):
            story += self._score_details(details, rubric, data)

        if last:
            notes = [
                ("Emp.", "delegaciones empatadas: comparten posición"),
                ("—", "sin nota: se listan al final, sin posición"),
                ("Premios", "asignados por la administración del evento"),
            ]
            story += [
                CondPageBreak(60),
                Spacer(1, 18),
                KeepTogether(
                    [
                        HRFlowable(width="100%", thickness=0.6, color=BORDER, spaceAfter=8),
                        note_line(notes),
                    ]
                ),
            ]
        return story

    @staticmethod
    def _awards_line(awards: list[Award], entries: dict[UUID, RankingEntry]) -> Flowable:
        """Premios del comité en una línea, o el aviso punteado si no tiene."""
        if awards:
            chips = "&nbsp;&nbsp;&nbsp;&nbsp;".join(
                award_markup(
                    a.award_type, f"&nbsp;—&nbsp;{e(delegation_name(entries[a.delegation_id]))}"
                )
                for a in awards
            )
            return p(chips, _style("chips", fontName=SANS_BOLD, fontSize=8, leading=14))
        callout = Table(
            [[p(NO_AWARDS_TEXT, S_MUTED)]], colWidths=[CONTENT_W], cornerRadii=[5, 5, 5, 5]
        )
        callout.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#C9D1DB"), 1, (2, 2)),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ]
            )
        )
        return callout

    # ------------------------------------------------------------ desglose y calificaciones

    @staticmethod
    def _section_title(title: str, subtitle: str) -> list[Flowable]:
        return [
            CondPageBreak(120),
            Spacer(1, 20),
            p(
                f'{e(title)}&nbsp;&nbsp;&nbsp;<font name="{SANS}" size="7.5" color="{MUTED_HEX}">'
                f"{e(subtitle)}</font>",
                _style("section", fontName=SERIF_BOLD, fontSize=11, textColor=NAVY),
            ),
            Spacer(1, 3),
        ]

    def _criteria_breakdown(
        self, committee: CommitteeResults, rubric: RubricInfo, *, include_scores: bool
    ) -> list[Flowable]:
        """Media de cada criterio de la rúbrica por delegación (casilla «Desglose por criterio»)."""
        criteria = sorted(rubric.criteria, key=lambda c: c.position)
        subtitle = (
            f"media de las calificaciones de cada criterio · escala {rubric.scale_min}–"
            f"{rubric.scale_max} · entre paréntesis, su peso"
        )
        header = ["POS.", "DELEGACIÓN"]
        header += [f"{c.name} ({c.weight.normalize():f} %)".upper() for c in criteria]
        fixed = [32, 128] + ([46] if include_scores else [])
        width = (CONTENT_W - sum(fixed)) / len(criteria)
        widths = fixed[:2] + [width] * len(criteria) + fixed[2:]
        if include_scores:
            header.append("NOTA")
        small_r = _style("crit_v", fontSize=8, alignment=TA_RIGHT)
        rows: list[list[object]] = []
        for entry in committee.ranking:
            row: list[object] = [
                p("–" if entry.score is None else str(entry.position), S_POS),
                p(delegation_markup(entry, muted=entry.score is None)),
            ]
            for c in criteria:
                value = entry.criteria_averages.get(c.id)
                row.append(p("—" if value is None else f"{present(value):.2f}", small_r))
            if include_scores:
                no_score = entry.score is None
                row.append(p(score_text(entry.score), S_RIGHT_MUTED if no_score else S_SCORE))
            rows.append(row)
        right = set(range(2, len(header)))
        return [
            *self._section_title("Desglose por criterio", subtitle),
            data_table(header, rows, widths, right=right),
        ]

    def _score_details(
        self, details: list[ScoreDetail], rubric: RubricInfo | None, data: ExportData
    ) -> list[Flowable]:
        """Calificaciones por delegado, sesión y juez (con nombres y comentarios si se piden)."""
        opts = data.options
        if rubric is not None and rubric.criteria:
            criteria = [c.name for c in sorted(rubric.criteria, key=lambda c: c.position)]
        else:
            criteria = list(dict.fromkeys(d.criterion for d in details))
        # Una fila por delegado × sesión × juez, en el orden del repositorio.
        groups: dict[tuple[str, str, int, str], dict[str, ScoreDetail]] = {}
        for d in details:
            groups.setdefault((d.delegation, d.delegate, d.session_number, d.judge), {})[
                d.criterion
            ] = d
        judges = "nombre del juez" if opts.include_judge_names else "jueces numerados por comité"
        subtitle = f"{len(details)} calificaciones · {judges}"
        if opts.include_comments:
            subtitle += " · con comentarios"

        header = ["DELEGACIÓN", "DELEGADO", "SES.", "JUEZ"] + [c.upper() for c in criteria]
        fixed_left = [84, 62, 24, 66]
        comments_w = 118 if opts.include_comments else 0
        width = max(34.0, (CONTENT_W - sum(fixed_left) - comments_w) / max(1, len(criteria)))
        widths = fixed_left + [width] * len(criteria)
        if opts.include_comments:
            header.append("COMENTARIOS")
            widths.append(CONTENT_W - sum(widths))
        value_style = _style("dv", fontSize=7.5, alignment=TA_RIGHT)
        rows: list[list[object]] = []
        for (delegation, delegate, session, judge), cells in groups.items():
            row: list[object] = [
                p(detail_delegation_markup(delegation), S_SMALL),
                p(e(format_name(delegate, data.name_format) or "—"), S_SMALL),
                p(str(session), _style("ds", fontName=MONO, fontSize=7.5, alignment=1)),
                p(e(judge), S_SMALL),
            ]
            row += [p(str(cells[c].value) if c in cells else "—", value_style) for c in criteria]
            if opts.include_comments:
                notes = [
                    f'<font name="{SANS_BOLD}">{e(c)}:</font> {e(cells[c].comment)}'
                    for c in criteria
                    if c in cells and cells[c].comment
                ]
                row.append(p("<br/>".join(notes), S_SMALL_MUTED))
            rows.append(row)
        right = set(range(4, 4 + len(criteria)))
        return [
            *self._section_title("Calificaciones por sesión", subtitle),
            data_table(header, rows, widths, right=right, compact=True),
        ]

    # ------------------------------------------------------------ utilidades

    @staticmethod
    def _belongs(detail: ScoreDetail, committee: CommitteeResults) -> bool:
        if detail.committee_id is not None:
            return detail.committee_id == committee.committee.id
        return detail.committee == committee.committee.name

    @staticmethod
    def _awards(committee: CommitteeResults) -> list[Award]:
        known = {entry.delegation.id for entry in committee.ranking}
        return [a for a in sort_awards(committee.awards) if a.delegation_id in known]

    @staticmethod
    def _names(entry: RankingEntry, name_format: NameFormat, sep: str) -> str:
        names = [format_name(d.full_name, name_format) for d in entry.delegates]
        return sep.join(n for n in names if n)

    @staticmethod
    def _names_markup(entry: RankingEntry, name_format: NameFormat) -> str:
        names = [format_name(d.full_name, name_format) for d in entry.delegates]
        shown = [e(n) for n in names if n]
        return "<br/>".join(shown) or "—"

    @staticmethod
    def _score_note(event_type: EventType) -> str:
        weights = weights_text(event_type, lower=True)
        if len(weights) <= 1:
            return "0–100, media de las sesiones con la rúbrica del comité"
        return "0–100, ponderada por rol (" + ", ".join(f"{r} {w} %" for r, w in weights) + ")"
