"""Plantillas de rúbrica para «Empezar la rúbrica desde» del asistente.

TODO(cliente): confirmar criterios y pesos con MUNYCH; son un punto de partida editable.
"""

import unicodedata
from typing import Any

from munych_api.modules.staff.schemas import RubricTemplate

TEMPLATES: dict[RubricTemplate, tuple[tuple[str, str, int], ...]] = {
    "press": (
        ("Calidad periodística", "Relevancia, veracidad y ángulo de las notas publicadas.", 30),
        ("Investigación y fuentes", "Uso de datos, citas y contraste de fuentes.", 25),
        ("Redacción y estilo", "Claridad, ortografía y estilo periodístico.", 20),
        ("Cobertura de comités", "Variedad de comités y momentos cubiertos.", 15),
        ("Puntualidad de entregas", "Entrega dentro de los cierres de edición.", 10),
    ),
    "position_papers": (
        ("Investigación y fundamentación", "Datos, fuentes y antecedentes del tema.", 30),
        ("Postura del país", "Coherencia con la política exterior de la delegación.", 25),
        ("Propuestas de solución", "Viabilidad y originalidad de las propuestas.", 25),
        ("Redacción y formato", "Estructura, ortografía y formato oficial.", 20),
    ),
    "oratory": (
        ("Claridad y dicción", "Se entiende el mensaje; volumen y ritmo adecuados.", 30),
        ("Argumentación", "Ideas sólidas, ordenadas y bien sustentadas.", 30),
        ("Lenguaje diplomático", "Registro formal y respeto al resto de delegaciones.", 20),
        ("Manejo del tiempo", "Aprovecha y respeta el tiempo concedido.", 20),
    ),
    "protocol": (
        ("Conducta y respeto", "Trato cordial con delegaciones, mesa y staff.", 40),
        ("Apego al protocolo", "Sigue el reglamento y las normas de vestimenta y sala.", 30),
        ("Trato al staff", "Colabora con pajes y logística durante las sesiones.", 30),
    ),
    "blank": (),
}

PALETTE = ("#418FDE", "#2F6BA8", "#C9A227", "#123B63", "#98A6B5")
"""Escala de pesos de MUN Scoring; el último es «sin configurar»."""


def template_criteria(template: RubricTemplate) -> list[dict[str, Any]]:
    return [
        {"id": f"c{i + 1}", "name": name, "description": desc, "weight": weight}
        for i, (name, desc, weight) in enumerate(TEMPLATES[template])
    ]


def initials(name: str) -> str:
    """«Pajes y protocolo» → «PP»; «Prensa» → «PR». Sin acentos, en mayúsculas."""
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    stop = {"y", "de", "del", "la", "las", "el", "los", "e"}
    words = [w for w in plain.split() if w.isalnum() and w.lower() not in stop]
    if len(words) >= 2:
        code = words[0][0] + words[1][0]
    elif words:
        code = words[0][:2]
    else:
        code = "ST"
    return code.upper()
