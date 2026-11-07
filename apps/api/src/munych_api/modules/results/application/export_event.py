"""Caso de uso: exportar los resultados del evento (Excel o CSV)."""

from dataclasses import dataclass, replace
from uuid import UUID

from munych_api.modules.results.application.close_event import committees_results, require_event
from munych_api.modules.results.application.ports import (
    Clock,
    ExportData,
    Exporter,
    ExportOptions,
    ResultsRepository,
    ScoreDetail,
)
from munych_api.shared.kernel.catalog import DEFAULT_EVENT_TYPE


@dataclass(frozen=True, slots=True)
class ExportFile:
    filename: str
    media_type: str
    content: bytes


def _apply_privacy(details: list[ScoreDetail], options: ExportOptions) -> list[ScoreDetail]:
    """Quita comentarios y/o cambia el nombre del juez por «Juez N» (numerado por comité)."""
    if options.include_comments and options.include_judge_names:
        return details
    aliases: dict[tuple[str, str], str] = {}
    counters: dict[str, int] = {}
    result = []
    for d in details:
        judge = d.judge
        if not options.include_judge_names:
            key = (d.committee, d.judge)
            if key not in aliases:
                counters[d.committee] = counters.get(d.committee, 0) + 1
                aliases[key] = f"Juez {counters[d.committee]}"
            judge = aliases[key]
        result.append(
            replace(d, judge=judge, comment=d.comment if options.include_comments else None)
        )
    return result


class ExportEvent:
    def __init__(self, repository: ResultsRepository, exporter: Exporter, clock: Clock) -> None:
        self._repo = repository
        self._exporter = exporter
        self._clock = clock

    async def execute(
        self, organization_id: UUID, event_id: UUID, options: ExportOptions | None = None
    ) -> ExportFile:
        options = options or ExportOptions()
        event = await require_event(self._repo, organization_id, event_id)
        committees = await committees_results(self._repo, organization_id, event_id)
        if options.committee_ids is not None:
            committees = [c for c in committees if c.committee.id in options.committee_ids]
        details: list[ScoreDetail] = []
        if options.include_details:
            names = {c.committee.name for c in committees}
            ids = {c.committee.id for c in committees}
            details = [
                d
                for d in await self._repo.score_details(event_id)
                if (d.committee_id in ids if d.committee_id is not None else d.committee in names)
            ]
            details = _apply_privacy(details, options)
        data = ExportData(
            event_name=event.name,
            venue=event.venue,
            starts_on=event.starts_on,
            ends_on=event.ends_on,
            timezone=event.timezone,
            generated_at=self._clock.now(),
            committees=committees,
            details=details,
            options=options,
            slug=event.slug,
            brand=event.brand,
            event_type=committees[0].event_type if committees else DEFAULT_EVENT_TYPE,
            name_format=event.publication_settings.name_format,
        )
        return ExportFile(
            filename=f"{event.slug}-resultados.{self._exporter.extension}",
            media_type=self._exporter.media_type,
            content=self._exporter.export(data),
        )
