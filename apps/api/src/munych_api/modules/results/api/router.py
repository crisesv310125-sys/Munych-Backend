from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from munych_api.modules.results.api.dependencies import (
    CloseEventDep,
    ComputeRankingDep,
    ExportEventCsvDep,
    ExportEventDep,
    ExportEventPdfDep,
    ManageAwardsDep,
    PublicationDep,
    SetTiebreakDep,
)
from munych_api.modules.results.api.schemas import (
    AwardIn,
    AwardOut,
    AwardsOut,
    CloseEventOut,
    IncompleteFlagOut,
    PublicationSettingsBody,
    PublicDocumentOut,
    PublishOut,
    RankingDelegateOut,
    RankingEntryOut,
    RankingOut,
    TiebreakIn,
    UnpublishOut,
)
from munych_api.modules.results.application.compute_ranking import CommitteeRanking
from munych_api.modules.results.application.export_event import ExportFile
from munych_api.modules.results.application.ports import ExportOptions
from munych_api.modules.results.application.set_awards import CommitteeAwards
from munych_api.modules.results.domain.models import Award, PublicationSettings, RankingEntry
from munych_api.modules.results.domain.snapshot import presented
from munych_api.modules.results.infrastructure.csv_exporter import CSV_MEDIA_TYPE
from munych_api.modules.results.infrastructure.excel_exporter import XLSX_MEDIA_TYPE
from munych_api.modules.results.infrastructure.pdf_exporter import PDF_MEDIA_TYPE
from munych_api.shared.auth import AdminUser, OrganizationId
from munych_api.shared.kernel.catalog import EVENT_TYPES

router = APIRouter(tags=["results"])


def _entry_out(entry: RankingEntry) -> RankingEntryOut:
    delegation = entry.delegation
    return RankingEntryOut(
        position=entry.position,
        tied=entry.tied,
        delegation_id=delegation.id,
        country_code=delegation.country_code,
        character_name=delegation.character_name,
        institution=delegation.institution,
        delegates=[
            RankingDelegateOut(
                delegate_id=d.delegate_id,
                full_name=d.full_name,
                final_score=presented(d.final_score),
            )
            for d in entry.delegates
        ],
        score=presented(entry.score),
        criteria_averages={str(k): presented(v) for k, v in entry.criteria_averages.items()},
        role_scores={role: presented(v) for role, v in entry.role_scores.items()},
        manual_tiebreak=entry.manual_tiebreak,
        incomplete_flags=[
            IncompleteFlagOut(
                kind=f.kind,
                delegate_id=f.delegate_id,
                session_number=f.session_number,
                judge_id=f.judge_id,
            )
            for f in entry.incomplete_flags
        ],
    )


def _awards_out(awards: CommitteeAwards) -> AwardsOut:
    return AwardsOut(
        items=[
            AwardOut(award_type=a.award_type, delegation_id=a.delegation_id, position=a.position)
            for a in awards.items
        ],
        quota_warnings=awards.quota_warnings,
    )


def _settings_body(settings: PublicationSettings) -> PublicationSettingsBody:
    return PublicationSettingsBody.model_validate(settings.to_dict())


# ---------------------------------------------------------------- ranking y premios


def _ranking_out(ranking: CommitteeRanking) -> RankingOut:
    return RankingOut(
        items=[_entry_out(e) for e in ranking.items],
        quota_warnings=ranking.quota_warnings,
        event_type=ranking.event_type,
        role_weights={
            role: float(weight)
            for role, weight in EVENT_TYPES[ranking.event_type].voter_weights.items()
        },
    )


@router.get("/committees/{committee_id}/ranking")
async def get_committee_ranking(
    committee_id: UUID, _: AdminUser, organization_id: OrganizationId, use_case: ComputeRankingDep
) -> RankingOut:
    """Ranking calculado con el motor puro + avisos de cupos de premios."""
    return _ranking_out(await use_case.execute(organization_id, committee_id))


@router.put("/committees/{committee_id}/tiebreak")
async def set_committee_tiebreak(
    committee_id: UUID,
    body: TiebreakIn,
    _: AdminUser,
    organization_id: OrganizationId,
    use_case: SetTiebreakDep,
) -> RankingOut:
    """Desempate manual: el admin ordena las delegaciones que siguen empatadas.

    Tras el desempate automático (criterio de mayor peso), los empates que queden los
    decide el admin. Se aplica en el ranking, la instantánea, la página pública y los
    exports. Devuelve el ranking ya recalculado.
    """
    return _ranking_out(await use_case.execute(organization_id, committee_id, body.delegation_ids))


@router.get("/committees/{committee_id}/awards")
async def list_committee_awards(
    committee_id: UUID, _: AdminUser, organization_id: OrganizationId, use_case: ManageAwardsDep
) -> AwardsOut:
    return _awards_out(await use_case.get(organization_id, committee_id))


@router.put("/committees/{committee_id}/awards")
async def replace_committee_awards(
    committee_id: UUID,
    body: list[AwardIn],
    user: AdminUser,
    organization_id: OrganizationId,
    use_case: ManageAwardsDep,
) -> AwardsOut:
    """Reemplaza los premios del comité. Superar un cupo solo genera avisos."""
    awards = [Award(a.award_type, a.delegation_id, a.position) for a in body]
    return _awards_out(await use_case.replace(organization_id, committee_id, awards, user.user_id))


# ---------------------------------------------------------------- cierre y exportación


@router.post("/events/{event_id}/close")
async def close_event(
    event_id: UUID, user: AdminUser, organization_id: OrganizationId, use_case: CloseEventDep
) -> CloseEventOut:
    """Exige todas las sesiones cerradas y guarda una instantánea inmutable."""
    closed = await use_case.execute(organization_id, event_id, user.user_id)
    return CloseEventOut(
        event_id=closed.event_id,
        status="closed",
        snapshot_id=closed.snapshot_id,
        closed_at=closed.closed_at,
    )


def export_options(
    committee_id: Annotated[
        list[UUID] | None,
        Query(description="Comités a exportar (repetible). Sin él: todos los del evento"),
    ] = None,
    include_scores: Annotated[
        bool, Query(description="Nota final ponderada (y por rol en CSV)")
    ] = True,
    include_details: Annotated[
        bool, Query(description="Hoja Detalle: cada calificación por sesión, juez y criterio")
    ] = True,
    include_comments: Annotated[
        bool, Query(description="Comentarios de los jueces en el Detalle (privados)")
    ] = True,
    include_judge_names: Annotated[
        bool, Query(description="Nombre del juez en el Detalle; si no, «Juez 1», «Juez 2»…")
    ] = True,
) -> ExportOptions:
    return ExportOptions(
        committee_ids=frozenset(committee_id) if committee_id else None,
        include_scores=include_scores,
        include_details=include_details,
        include_comments=include_comments,
        include_judge_names=include_judge_names,
    )


ExportOptionsDep = Annotated[ExportOptions, Depends(export_options)]


def _download(export: ExportFile) -> Response:
    return Response(
        content=export.content,
        media_type=export.media_type,
        headers={"Content-Disposition": f'attachment; filename="{export.filename}"'},
    )


@router.get(
    "/events/{event_id}/export.xlsx",
    response_class=Response,
    responses={200: {"content": {XLSX_MEDIA_TYPE: {}}, "description": "Libro de Excel"}},
)
async def export_event_xlsx(
    event_id: UUID,
    _: AdminUser,
    organization_id: OrganizationId,
    use_case: ExportEventDep,
    options: ExportOptionsDep,
) -> Response:
    """Hoja Resumen, una hoja de ranking por comité y (opcional) hoja Detalle por criterio."""
    return _download(await use_case.execute(organization_id, event_id, options))


@router.get(
    "/events/{event_id}/export.csv",
    response_class=Response,
    responses={200: {"content": {CSV_MEDIA_TYPE: {}}, "description": "Ranking en CSV"}},
)
async def export_event_csv(
    event_id: UUID,
    _: AdminUser,
    organization_id: OrganizationId,
    use_case: ExportEventCsvDep,
    options: ExportOptionsDep,
) -> Response:
    """Ranking de todos los comités en una tabla plana (UTF-8 con BOM, separado por comas).

    Columnas: comité, siglas, posición, empate, delegación, institución, delegados, nota
    (y nota por rol si el evento tiene varios), premios y avisos. Sin detalle por juez.
    """
    return _download(await use_case.execute(organization_id, event_id, options))


@router.get(
    "/events/{event_id}/export.pdf",
    response_class=Response,
    responses={200: {"content": {PDF_MEDIA_TYPE: {}}, "description": "Acta de resultados"}},
)
async def export_event_pdf(
    event_id: UUID,
    _: AdminUser,
    organization_id: OrganizationId,
    use_case: ExportEventPdfDep,
    options: ExportOptionsDep,
) -> Response:
    """Acta de resultados oficial (según la muestra de MUNYCH).

    Portada con los datos del evento y el resumen de premiación; luego una sección por
    comité con sus premios y su ranking. Los nombres de los delegados siguen el formato de
    la publicación (por defecto, nombre e inicial). Respeta todas las opciones:
    `include_details` añade el desglose por criterio y las calificaciones por sesión,
    `include_judge_names` los nombres de los jueces (si no, «Juez N») e `include_comments`
    sus comentarios; con jueces o comentarios, la portada avisa de que es un documento
    interno. ⚠️ Por defecto todo es `true`: el panel siempre manda sus casillas.
    """
    return _download(await use_case.execute(organization_id, event_id, options))


# ---------------------------------------------------------------- publicación


@router.get("/events/{event_id}/publication-settings")
async def get_publication_settings(
    event_id: UUID, _: AdminUser, organization_id: OrganizationId, use_case: PublicationDep
) -> PublicationSettingsBody:
    return _settings_body(await use_case.get_settings(organization_id, event_id))


@router.put("/events/{event_id}/publication-settings")
async def update_publication_settings(
    event_id: UUID,
    body: PublicationSettingsBody,
    _: AdminUser,
    organization_id: OrganizationId,
    use_case: PublicationDep,
) -> PublicationSettingsBody:
    settings = PublicationSettings(**body.model_dump())
    return _settings_body(await use_case.update_settings(organization_id, event_id, settings))


@router.get("/events/{event_id}/publication/preview")
async def preview_publication(
    event_id: UUID, _: AdminUser, organization_id: OrganizationId, use_case: PublicationDep
) -> PublicDocumentOut:
    """El documento público que se publicaría ahora (no se guarda)."""
    return PublicDocumentOut.model_validate(await use_case.preview(organization_id, event_id))


@router.post("/events/{event_id}/publish")
async def publish_event(
    event_id: UUID, _: AdminUser, organization_id: OrganizationId, use_case: PublicationDep
) -> PublishOut:
    """Publica en `public_results` y avisa al sitio. Si el aviso falla, `revalidated=false`."""
    result = await use_case.publish(organization_id, event_id)
    return PublishOut(
        version=result.version, published_at=result.published_at, revalidated=result.revalidated
    )


@router.post("/events/{event_id}/unpublish")
async def unpublish_event(
    event_id: UUID, _: AdminUser, organization_id: OrganizationId, use_case: PublicationDep
) -> UnpublishOut:
    return UnpublishOut(revalidated=await use_case.unpublish(organization_id, event_id))
