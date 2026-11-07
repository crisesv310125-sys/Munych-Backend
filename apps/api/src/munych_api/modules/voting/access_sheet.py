"""Hoja imprimible de accesos de votación en PDF (2026-11-07).

Reproduce la muestra que entregó MUNYCH («Accesos de votación MUNYCH - muestra»): carta,
agrupada por comité, 9 tarjetas recortables por hoja (3 × 3, línea punteada). Cada tarjeta:
cabecera azul con la marca y el evento, «ACCESO DE VOTACIÓN · AG · 01/32», el QR del enlace,
el nombre del delegado, su delegación, y el código corto de respaldo con la dirección donde
escribirlo si la cámara no lee el QR.

Los tokens en claro solo existen al generarlos: la hoja se dibuja con los que manda el panel
justo después de generarlos (el servicio comprueba que sean los vigentes). Se dibuja con el
canvas de reportlab y las fuentes estándar del PDF; el QR es vectorial (segno → rectángulos),
nítido a cualquier escala de impresión.
"""

import io
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import groupby

import segno
from babel import Locale
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

PDF_MEDIA_TYPE = "application/pdf"

NAVY = colors.HexColor("#14304F")
INK = colors.HexColor("#1F2A37")
MUTED = colors.HexColor("#6B7A8C")
LINK = colors.HexColor("#2F6FCB")
GOLD = colors.HexColor("#C9A227")
CUT = colors.HexColor("#A9B4C2")
BOX_BG = colors.HexColor("#F3F5F8")
BOX_BORDER = colors.HexColor("#E2E7ED")
WHITE = colors.white

SERIF_BOLD = "Times-Bold"
SANS, SANS_BOLD = "Helvetica", "Helvetica-Bold"
MONO = "Courier-Bold"

PAGE_W, PAGE_H = LETTER
MARGIN_X = 40.0
GRID_TOP = PAGE_H - 70
COLS, ROWS = 3, 3
CELL_W = (PAGE_W - 2 * MARGIN_X) / COLS
CELL_H = 228.0
PAD = 6.0
QR_SIZE = 96.0
"""≈ 3.4 cm: por encima del mínimo de 2.5 cm para leerlo impreso."""

BRANDS = {"munych": "MUNYCH", "grand_international": "GRAND"}
BRAND_FULL = {"munych": "MUNYCH", "grand_international": "GRAND INTERNATIONAL"}

_COUNTRIES = Locale("es").territories


@dataclass(frozen=True, slots=True)
class AccessCard:
    full_name: str
    delegation: str
    """Nombre del país en español o del personaje."""
    committee_name: str
    committee_acronym: str
    url: str
    code: str


def delegation_label(country_code: str | None, character_name: str | None) -> str:
    if character_name:
        return character_name
    if country_code:
        return str(_COUNTRIES.get(country_code.upper(), country_code))
    return "—"


def sort_key(text: str) -> str:
    """Orden alfabético sin acentos (Á antes que B, como en la muestra)."""
    return unicodedata.normalize("NFD", text).encode("ascii", "ignore").decode().casefold()


def entry_address(url: str, token: str) -> str:
    """Dónde escribir el código: el enlace sin el token ni el protocolo."""
    base = url[: -len(token)] if token and url.endswith(token) else url
    return base.removeprefix("https://").removeprefix("http://").rstrip("/")


def spaced(text: str) -> str:
    return "   ".join(" ".join(word) for word in text.upper().split())


def fit(text: str, font: str, size: float, width: float, minimum: float = 6.0) -> float:
    """Tamaño de letra para que el texto quepa en `width` (sin bajar de `minimum`)."""
    while size > minimum and stringWidth(text, font, size) > width:
        size -= 0.25
    return size


def ellipsize(text: str, font: str, size: float, width: float) -> str:
    if stringWidth(text, font, size) <= width:
        return text
    while text and stringWidth(text + "…", font, size) > width:
        text = text[:-1]
    return text + "…"


# ---------------------------------------------------------------- dibujo


def draw_monogram(c: Canvas, x: float, y: float, radius: float, letter: str) -> None:
    c.setFillColor(NAVY)
    c.setStrokeColor(GOLD)
    c.setLineWidth(max(0.8, radius / 9))
    c.circle(x, y, radius, stroke=1, fill=1)
    c.setFillColor(GOLD)
    c.setFont(SERIF_BOLD, radius * 1.15)
    c.drawCentredString(x, y - radius * 0.4, letter)


def draw_qr(c: Canvas, url: str, x: float, y: float, size: float) -> None:
    """QR vectorial: un rectángulo por módulo oscuro (corrección media, margen blanco)."""
    qr = segno.make(url, error="m")
    matrix = [list(row) for row in qr.matrix]
    modules = len(matrix)
    cell = size / modules
    c.setFillColor(colors.black)
    for r, row in enumerate(matrix):
        start = None
        for col, dark in enumerate([*row, 0]):
            if dark and start is None:
                start = col
            elif not dark and start is not None:
                # Une módulos contiguos de la fila: menos objetos y sin rayitas entre ellos.
                c.rect(
                    x + start * cell,
                    y + size - (r + 1) * cell,
                    (col - start) * cell,
                    cell,
                    stroke=0,
                    fill=1,
                )
                start = None


def draw_page_header(
    c: Canvas,
    *,
    brand: str,
    event_name: str,
    committee: str,
    total: int,
    sheet: int,
    sheets: int,
) -> None:
    top = PAGE_H - 30
    draw_monogram(c, MARGIN_X + 14, top - 10, 13, brand[:1] or "M")
    x = MARGIN_X + 34
    c.setFillColor(MUTED)
    c.setFont(SANS, 6)
    c.drawString(x, top - 2, spaced(f"{brand} · {event_name} · Accesos de votación"))
    c.setFillColor(NAVY)
    title_size = fit(committee, SERIF_BOLD, 15, PAGE_W * 0.55)
    c.setFont(SERIF_BOLD, title_size)
    c.drawString(x, top - 19, committee)
    offset = stringWidth(committee, SERIF_BOLD, title_size)
    c.setFillColor(MUTED)
    c.setFont(SANS, 8.5)
    c.drawString(x + offset + 3, top - 19, f"· {total} {'acceso' if total == 1 else 'accesos'}")

    right = PAGE_W - MARGIN_X
    c.setFillColor(NAVY)
    c.setFont(SANS_BOLD, 8)
    c.drawRightString(right, top - 6, f"HOJA {sheet} DE {sheets}")
    c.setFillColor(MUTED)
    c.setFont(SANS, 6)
    c.drawRightString(right, top - 16, "Imprime al 100 % y recorta por la línea punteada")


def draw_card(
    c: Canvas,
    card: AccessCard,
    *,
    x: float,
    y: float,
    brand: str,
    event_name: str,
    index: int,
    total: int,
    token: str,
) -> None:
    """Una tarjeta en la celda cuya esquina inferior izquierda es (x, y)."""
    # Línea de corte.
    c.setStrokeColor(CUT)
    c.setLineWidth(0.6)
    c.setDash(2, 2)
    c.rect(x, y, CELL_W, CELL_H, stroke=1, fill=0)
    c.setDash()

    left, right = x + PAD, x + CELL_W - PAD
    width = right - left
    center = x + CELL_W / 2
    top = y + CELL_H - PAD
    label_y = _draw_card_header(c, left, right, top, brand=brand, event_name=event_name)

    c.setFillColor(MUTED)
    c.setFont(SANS, 5.5)
    c.drawString(left + 2, label_y, spaced("Acceso de votación"))
    c.drawRightString(
        right - 2, label_y, spaced(f"{card.committee_acronym} · {index:02d}/{total:02d}")
    )

    # QR, con margen blanco alrededor (la cámara lo necesita para encontrarlo).
    qr_top = label_y - 8
    draw_qr(c, card.url, center - QR_SIZE / 2, qr_top - QR_SIZE, QR_SIZE)

    # Nombre, delegación e instrucción.
    name_y = qr_top - QR_SIZE - 15
    name_size = fit(card.full_name, SERIF_BOLD, 11.5, width - 6)
    c.setFillColor(NAVY)
    c.setFont(SERIF_BOLD, name_size)
    c.drawCentredString(center, name_y, ellipsize(card.full_name, SERIF_BOLD, name_size, width - 6))
    delegation = f"{card.delegation} · {card.committee_acronym}"
    delegation_size = fit(delegation, SANS, 8, width - 6)
    c.setFillColor(INK)
    c.setFont(SANS, delegation_size)
    c.drawCentredString(
        center, name_y - 10, ellipsize(delegation, SANS, delegation_size, width - 6)
    )
    c.setFillColor(MUTED)
    c.setFont(SANS, 5.8)
    c.drawCentredString(center, name_y - 19, "Escanea para votar · personal e intransferible")

    _draw_code_box(c, left, width, y + PAD, address=entry_address(card.url, token), code=card.code)


def _draw_card_header(
    c: Canvas, left: float, right: float, top: float, *, brand: str, event_name: str
) -> float:
    """Cabecera azul con la marca y el evento, y filete dorado. Devuelve la y del rótulo."""
    width = right - left
    bar_h = 22.0
    c.setFillColor(NAVY)
    c.roundRect(left, top - bar_h, width, bar_h, 4, stroke=0, fill=1)
    c.rect(left, top - bar_h, width, 4, stroke=0, fill=1)  # esquinas inferiores rectas
    c.setFillColor(GOLD)
    c.rect(left, top - bar_h - 1.6, width, 1.6, stroke=0, fill=1)
    draw_monogram(c, left + 12, top - bar_h / 2, 6.5, brand[:1] or "M")
    c.setFillColor(WHITE)
    c.setFont(SERIF_BOLD, 9)
    c.drawString(left + 23, top - bar_h / 2 - 3, brand)
    c.setFont(SANS, 5.8)
    event_text = spaced(event_name)
    c.drawRightString(
        right - 7,
        top - bar_h / 2 - 2,
        ellipsize(event_text, SANS, 5.8, width * 0.55),
    )
    return top - bar_h - 11


def _draw_code_box(
    c: Canvas, left: float, width: float, box_y: float, *, address: str, code: str
) -> None:
    """Recuadro gris con la dirección donde escribir el código y el código de respaldo."""
    center = left + width / 2
    box_h = 42.0
    c.setFillColor(BOX_BG)
    c.setStrokeColor(BOX_BORDER)
    c.setLineWidth(0.6)
    c.roundRect(left, box_y, width, box_h, 4, stroke=1, fill=1)
    c.setFillColor(MUTED)
    c.setFont(SANS, 5.8)
    c.drawCentredString(center, box_y + box_h - 9, "¿No lee el QR? Entra a")
    suffix = " y escribe:"
    address_size = fit(address + suffix, SANS_BOLD, 5.8, width - 8, minimum=4.5)
    address = ellipsize(
        address, SANS_BOLD, address_size, width - 8 - stringWidth(suffix, SANS, address_size)
    )
    line = stringWidth(address, SANS_BOLD, address_size) + stringWidth(suffix, SANS, address_size)
    start = center - line / 2
    c.setFillColor(LINK)
    c.setFont(SANS_BOLD, address_size)
    c.drawString(start, box_y + box_h - 17, address)
    c.setFillColor(MUTED)
    c.setFont(SANS, address_size)
    c.drawString(start + stringWidth(address, SANS_BOLD, address_size), box_y + box_h - 17, suffix)
    c.setFillColor(NAVY)
    code_size = fit(code, MONO, 15, width - 10)
    c.setFont(MONO, code_size)
    c.drawCentredString(center, box_y + 8, code)


def render_access_sheet(
    *, event_name: str, brand: str, cards: Sequence[AccessCard], tokens: Sequence[str]
) -> bytes:
    """PDF con las tarjetas agrupadas por comité, en el orden recibido (ya ordenado).

    `tokens[i]` es el token de `cards[i]` (solo para quitarlo del enlace al mostrar la
    dirección donde escribir el código; nunca se imprime aparte).
    """
    buffer = io.BytesIO()
    c = Canvas(buffer, pagesize=LETTER)
    short = BRANDS.get(brand, brand.upper())
    c.setTitle(f"{event_name} · Accesos de votación")
    c.setAuthor(BRAND_FULL.get(brand, brand))
    c.setSubject("Accesos de votación (personales e intransferibles)")

    pairs = list(zip(cards, tokens, strict=True))
    per_page = COLS * ROWS
    first = True
    committee_of = lambda pair: (pair[0].committee_name, pair[0].committee_acronym)  # noqa: E731
    for _, group_iter in groupby(pairs, key=committee_of):
        group = list(group_iter)
        total = len(group)
        sheets = (total + per_page - 1) // per_page
        committee = f"{group[0][0].committee_name} ({group[0][0].committee_acronym})"
        for sheet in range(sheets):
            if not first:
                c.showPage()
            first = False
            draw_page_header(
                c,
                brand=short,
                event_name=event_name,
                committee=committee,
                total=total,
                sheet=sheet + 1,
                sheets=sheets,
            )
            for slot, (card, token) in enumerate(group[sheet * per_page : (sheet + 1) * per_page]):
                row, col = divmod(slot, COLS)
                draw_card(
                    c,
                    card,
                    x=MARGIN_X + col * CELL_W,
                    y=GRID_TOP - (row + 1) * CELL_H,
                    brand=short,
                    event_name=event_name,
                    index=sheet * per_page + slot + 1,
                    total=total,
                    token=token,
                )
    if first:  # sin accesos: una hoja que lo dice
        c.setFont(SANS, 10)
        c.drawString(MARGIN_X, PAGE_H - 60, "No hay accesos que imprimir.")
    c.save()
    return buffer.getvalue()
