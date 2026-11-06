"""Tokens de acceso de los delegados (ADR-005): aleatorios, guardados como hash.

El token en claro solo existe en la respuesta que lo genera (y en el QR o enlace
que el admin reparte). En la base solo queda su SHA-256: quien lea la base no
puede votar por nadie.
"""

import hashlib
import secrets
from datetime import UTC, date, datetime, time, timedelta

import segno

TOKEN_BYTES = 24
"""24 bytes aleatorios → 32 caracteres base64url (192 bits): no se puede adivinar."""

EXPIRY_MARGIN = timedelta(days=2)
"""Los tokens vencen dos días después del último día del evento (margen por zona horaria)."""

QR_SCALE = 4


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def looks_like_token(value: str) -> bool:
    """Filtro barato antes de ir a la base (longitud y alfabeto base64url)."""
    return 20 <= len(value) <= 64 and all(c.isalnum() or c in "-_" for c in value)


def expires_at(ends_on: date) -> datetime:
    return datetime.combine(ends_on, time.min, tzinfo=UTC) + EXPIRY_MARGIN


def qr_svg(url: str) -> str:
    """QR del enlace como SVG en línea (para imprimir en gafetes o papeletas)."""
    return str(segno.make(url, error="m").svg_inline(scale=QR_SCALE, border=2))
