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

CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
"""Sin 0/O ni 1/I/L: se dicta y se escribe a mano sin confusiones."""

CODE_LENGTH = 10
"""31^10 ≈ 8·10^14 combinaciones (~50 bits): no se puede adivinar probando."""


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def looks_like_token(value: str) -> bool:
    """Filtro barato antes de ir a la base (longitud y alfabeto base64url)."""
    return 20 <= len(value) <= 64 and all(c.isalnum() or c in "-_" for c in value)


# ---------------------------------------------------------------- código corto de respaldo


def new_code() -> str:
    """Código de respaldo para escribir a mano si la cámara no lee el QR, p. ej. `K7M2Q-9XH4T`."""
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
    half = CODE_LENGTH // 2
    return f"{raw[:half]}-{raw[half:]}"


def normalize_code(value: str) -> str | None:
    """El código sin guiones ni espacios y en mayúsculas, o `None` si no tiene la forma de uno."""
    code = "".join(c for c in value.upper() if c.isalnum())
    if len(code) != CODE_LENGTH or any(c not in CODE_ALPHABET for c in code):
        return None
    return code


def hash_code(code: str) -> str:
    """Hash del código normalizado (con prefijo: nunca coincide con el de un token)."""
    return hashlib.sha256(f"code:{code}".encode()).hexdigest()


def expires_at(ends_on: date) -> datetime:
    return datetime.combine(ends_on, time.min, tzinfo=UTC) + EXPIRY_MARGIN


def qr_svg(url: str) -> str:
    """QR del enlace como SVG en línea (para imprimir en gafetes o papeletas)."""
    return str(segno.make(url, error="m").svg_inline(scale=QR_SCALE, border=2))
