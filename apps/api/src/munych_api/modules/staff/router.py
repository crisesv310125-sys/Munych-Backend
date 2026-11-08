from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response

from munych_api.modules.staff.dependencies import CurrentStaffPerson, StaffServiceDep
from munych_api.modules.staff.schemas import (
    AccessLinkIn,
    AccessLinkOut,
    AssignAwardIn,
    AwardIn,
    AwardPatch,
    ConfirmAwardsIn,
    EventStaffMemberOut,
    MemberIn,
    MemberPatch,
    PersonOut,
    PersonPatch,
    RankingOut,
    RubricIn,
    StaffEvaluationIn,
    StaffEvaluationOut,
    StaffInviteIn,
    StaffInviteOut,
    StaffMeOut,
    StaffOverviewOut,
    StaffTypeDetailOut,
    StaffTypeIn,
    StaffTypePatch,
)
from munych_api.shared.auth import AdminUser, OrganizationId
from munych_api.shared.rate_limit import (
    BALLOT_LIMIT,
    INVITES_LIMIT,
    STAFF_EVALUATIONS_LIMIT,
    limiter,
    voter_key,
)

router = APIRouter(tags=["staff"])

EventContext = Annotated[
    UUID | None,
    Query(
        description="Evento de contexto para candidatos, avance y premios. "
        "Si se omite: el evento activo más reciente de la organización"
    ),
]

# El staff es de la organización (no de un evento): tipos, personas, rúbricas y premios.

# ---------------------------------------------------------------- tipos de staff (admin)


@router.get("/staff")
async def staff_overview(
    _: AdminUser,
    organization_id: OrganizationId,
    service: StaffServiceDep,
    event_id: EventContext = None,
) -> StaffOverviewOut:
    """Tipos de staff de la organización con su avance y premios en un evento (pantalla 01)."""
    return await service.overview(organization_id, event_id)


@router.post("/staff-types", status_code=201)
async def create_staff_type(
    body: StaffTypeIn,
    _: AdminUser,
    organization_id: OrganizationId,
    service: StaffServiceDep,
    event_id: EventContext = None,
) -> StaffTypeDetailOut:
    """Nuevo tipo de staff (asistente). La rúbrica empieza desde la plantilla elegida."""
    return await service.create_type(organization_id, body, event_id)


@router.get("/staff-types/{type_id}")
async def get_staff_type(
    type_id: UUID,
    _: AdminUser,
    organization_id: OrganizationId,
    service: StaffServiceDep,
    event_id: EventContext = None,
) -> StaffTypeDetailOut:
    return await service.detail(organization_id, type_id, event_id)


@router.patch("/staff-types/{type_id}")
async def update_staff_type(
    type_id: UUID,
    body: StaffTypePatch,
    _: AdminUser,
    organization_id: OrganizationId,
    service: StaffServiceDep,
    event_id: EventContext = None,
) -> StaffTypeDetailOut:
    """Configuración del tipo. `archived: true` lo oculta sin borrar nada."""
    return await service.update_type(organization_id, type_id, body, event_id)


@router.put("/staff-types/{type_id}/rubric")
async def put_staff_rubric(
    type_id: UUID,
    body: RubricIn,
    _: AdminUser,
    organization_id: OrganizationId,
    service: StaffServiceDep,
    event_id: EventContext = None,
) -> StaffTypeDetailOut:
    """Reemplaza la rúbrica. Los pesos deben sumar 100 (422 si no). Cambiar pesos con
    evaluaciones recalcula las notas; cambiar la escala con evaluaciones da 409."""
    return await service.put_rubric(organization_id, type_id, body, event_id)


# ---------------------------------------------------------------- miembros (admin)


@router.get("/staff-people")
async def list_staff_people(
    _: AdminUser, organization_id: OrganizationId, service: StaffServiceDep
) -> list[PersonOut]:
    """Personas del staff y jueces de la organización (para «Añadir otra persona»)."""
    return await service.people(organization_id)


@router.post("/staff-types/{type_id}/members", status_code=201)
async def add_staff_member(
    type_id: UUID,
    body: MemberIn,
    _: AdminUser,
    organization_id: OrganizationId,
    service: StaffServiceDep,
    event_id: EventContext = None,
) -> StaffTypeDetailOut:
    return await service.add_member(organization_id, type_id, body, event_id)


@router.patch("/staff-members/{member_id}")
async def update_staff_member(
    member_id: UUID,
    body: MemberPatch,
    _: AdminUser,
    organization_id: OrganizationId,
    service: StaffServiceDep,
    event_id: EventContext = None,
) -> StaffTypeDetailOut:
    return await service.update_member(organization_id, member_id, body, event_id)


@router.post("/staff-members/{member_id}/remove")
async def remove_staff_member(
    member_id: UUID,
    _: AdminUser,
    organization_id: OrganizationId,
    service: StaffServiceDep,
    event_id: EventContext = None,
) -> StaffTypeDetailOut:
    """Quita al miembro del tipo. No borra sus evaluaciones."""
    return await service.remove_member(organization_id, member_id, event_id)


@router.patch("/staff-people/{person_id}")
async def update_staff_person(
    person_id: UUID,
    body: PersonPatch,
    _: AdminUser,
    organization_id: OrganizationId,
    service: StaffServiceDep,
) -> PersonOut:
    return await service.update_person(organization_id, person_id, body)


@router.post("/staff-people/{person_id}/link")
async def issue_staff_link(
    person_id: UUID,
    body: AccessLinkIn,
    _: AdminUser,
    organization_id: OrganizationId,
    service: StaffServiceDep,
) -> AccessLinkOut:
    """Genera el enlace personal de evaluación. El token solo se devuelve aquí; el
    enlace anterior de la persona deja de servir."""
    return await service.issue_link(organization_id, person_id, body)


# ---------------------------------------------------------------- ranking y premios (admin)


@router.get("/staff-types/{type_id}/ranking")
async def staff_ranking(
    type_id: UUID,
    _: AdminUser,
    organization_id: OrganizationId,
    service: StaffServiceDep,
    event_id: EventContext = None,
    committee_id: UUID | None = Query(default=None, description="Solo los de este comité"),
) -> RankingOut:
    """Ranking de candidatos del evento (sugiere premios) y premios con sus lugares."""
    return await service.ranking(organization_id, type_id, event_id, committee_id)


@router.post("/staff-types/{type_id}/awards", status_code=201)
async def add_staff_award(
    type_id: UUID,
    body: AwardIn,
    _: AdminUser,
    organization_id: OrganizationId,
    service: StaffServiceDep,
    event_id: EventContext = None,
) -> StaffTypeDetailOut:
    return await service.add_award(organization_id, type_id, body, event_id)


@router.patch("/staff-awards/{award_id}")
async def update_staff_award(
    award_id: UUID,
    body: AwardPatch,
    _: AdminUser,
    organization_id: OrganizationId,
    service: StaffServiceDep,
    event_id: EventContext = None,
) -> StaffTypeDetailOut:
    """Edita el premio. `archived: true` lo quita sin borrar nada."""
    return await service.update_award(organization_id, award_id, body, event_id)


@router.put("/staff-awards/{award_id}/assignment")
async def assign_staff_award(
    award_id: UUID,
    body: AssignAwardIn,
    user: AdminUser,
    organization_id: OrganizationId,
    service: StaffServiceDep,
) -> RankingOut:
    """Asigna (o deja vacío) un lugar del premio en un evento. Puede ser otro candidato
    que el sugerido: se guarda quién lo asignó, el sugerido y el motivo."""
    return await service.assign_award(organization_id, award_id, body, user.user_id)


@router.post("/staff-types/{type_id}/awards/confirm")
async def confirm_staff_awards(
    type_id: UUID,
    body: ConfirmAwardsIn,
    user: AdminUser,
    organization_id: OrganizationId,
    service: StaffServiceDep,
) -> StaffTypeDetailOut:
    """Congela los premios del staff en el evento (todos asignados) o los reabre."""
    return await service.confirm_awards(organization_id, type_id, body, user.user_id)


# ---------------------------------------------------------------- personas del evento


@router.get("/events/{event_id}/staff-members")
async def list_event_staff(
    event_id: UUID, _: AdminUser, organization_id: OrganizationId, service: StaffServiceDep
) -> list[EventStaffMemberOut]:
    """Personas del staff asignadas al evento, con su tipo y el estado de su acceso."""
    return await service.event_members(organization_id, event_id)


@router.post("/events/{event_id}/invitations", status_code=201)
@limiter.limit(INVITES_LIMIT)
async def invite_to_event(
    request: Request,
    event_id: UUID,
    body: StaffInviteIn,
    _: AdminUser,
    organization_id: OrganizationId,
    service: StaffServiceDep,
) -> StaffInviteOut:
    """Invita a alguien al evento con su rol: juez o un tipo de staff.

    Juez y tipos con cuenta (Mesa Directiva): correo para crear contraseña (plantilla
    «Invite user»). Tipos sin cuenta: correo con su QR de acceso (plantilla «Magic Link»).
    """
    return await service.invite(organization_id, event_id, body)


@router.post("/staff-members/{member_id}/access")
@limiter.limit(INVITES_LIMIT)
async def resend_staff_access(
    request: Request,
    member_id: UUID,
    _: AdminUser,
    organization_id: OrganizationId,
    service: StaffServiceDep,
) -> StaffInviteOut:
    """Genera un QR nuevo (el anterior deja de servir) y lo reenvía por correo."""
    return await service.resend_access(organization_id, member_id)


@router.get(
    "/staff/qr/{token}.png",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}, "description": "QR del enlace personal"}},
)
async def staff_qr(token: str, service: StaffServiceDep) -> Response:
    """Imagen del QR que se muestra en el correo del staff. Solo con un token vigente."""
    return Response(
        content=await service.qr_png(token),
        media_type="image/png",
        headers={"Cache-Control": "private, no-store"},
    )


# ---------------------------------------------------------------- miembro del staff (enlace)


@router.get("/staff/me")
@limiter.limit(BALLOT_LIMIT, key_func=voter_key)
async def staff_me(
    request: Request, person: CurrentStaffPerson, service: StaffServiceDep
) -> StaffMeOut:
    """Lo que le toca evaluar a la persona del enlace en los eventos abiertos."""
    return await service.me(person)


@router.put("/staff/evaluations")
@limiter.limit(STAFF_EVALUATIONS_LIMIT, key_func=voter_key)
async def save_staff_evaluation(
    request: Request,
    body: StaffEvaluationIn,
    person: CurrentStaffPerson,
    service: StaffServiceDep,
) -> StaffEvaluationOut:
    """Autoguardado de una evaluación (valores parciales o completos)."""
    return await service.save_evaluation(person, body)
