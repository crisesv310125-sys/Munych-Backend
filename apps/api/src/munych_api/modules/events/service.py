import uuid
from typing import Any
from uuid import UUID

from munych_api.modules.events.csv_import import CsvRowError, parse_delegations_csv
from munych_api.modules.events.repository import EventsRepository
from munych_api.modules.events.schemas import (
    CommitteeCreate,
    CommitteeOut,
    CommitteeUpdate,
    DelegateIn,
    DelegateOut,
    DelegateUpdate,
    DelegationCreate,
    DelegationOut,
    DelegationUpdate,
    EventCreate,
    EventOut,
    EventUpdate,
    ImportResult,
    ImportRowError,
)
from munych_api.modules.rubrics.service import RubricsService, default_rubric
from munych_api.shared.kernel import DomainError, ErrorCode, NotFoundError
from munych_api.shared.kernel.catalog import (
    DEFAULT_AWARD_QUOTAS,
    EVENT_LOGOS_BUCKET,
    LOGO_CONTENT_TYPES,
    LOGO_MAX_BYTES,
    MAX_DELEGATES,
    AwardType,
    CommitteeType,
    DelegationMode,
)
from munych_api.shared.pagination import Page, PageParams
from munych_api.shared.supabase import ObjectStorage


def _ensure_not_closed(status: str) -> None:
    # Cerrar el evento congela resultados: cualquier cambio en cascada tocaría
    # calificaciones o premios (sección 6.5).
    if status == "closed":
        raise DomainError(ErrorCode.EVENT_CLOSED, "El evento está cerrado")


def _quotas(
    committee_type: CommitteeType, quotas: dict[AwardType, int] | None
) -> dict[AwardType, int]:
    return {**DEFAULT_AWARD_QUOTAS[committee_type], **(quotas or {})}


def _delegates_limit_error(mode: DelegationMode) -> DomainError:
    limit = MAX_DELEGATES[mode]
    kind = "individual" if mode == "single" else "doble"
    return DomainError(
        ErrorCode.DELEGATES_LIMIT_EXCEEDED,
        f"Una delegación {kind} admite como máximo {limit} delegado{'s' if limit > 1 else ''}",
    )


class EventsService:
    def __init__(
        self, repository: EventsRepository, rubrics: RubricsService, storage: ObjectStorage
    ) -> None:
        self._repo = repository
        self._rubrics = rubrics
        self._storage = storage

    # ------------------------------------------------------------ eventos

    def _event_out(self, row: dict[str, Any]) -> EventOut:
        logo_path = row.get("logo_path")
        return EventOut(
            **{k: row[k] for k in EventOut.model_fields if k in row},
            logo_url=self._storage.public_url(EVENT_LOGOS_BUCKET, logo_path) if logo_path else None,
        )

    async def _require_event(self, organization_id: UUID, event_id: UUID) -> dict[str, Any]:
        event = await self._repo.get_event(event_id, organization_id)
        if event is None:
            raise NotFoundError("Evento no encontrado")
        return event

    async def list_events(self, organization_id: UUID, page: PageParams) -> Page[EventOut]:
        rows, total = await self._repo.list_events(organization_id, page.limit, page.offset)
        return Page[EventOut](items=[self._event_out(r) for r in rows], total=total)

    async def get_event(self, organization_id: UUID, event_id: UUID) -> EventOut:
        return self._event_out(await self._require_event(organization_id, event_id))

    async def create_event(self, organization_id: UUID, data: EventCreate) -> EventOut:
        if await self._repo.slug_exists(data.slug):
            raise DomainError(ErrorCode.CONFLICT, f"Ya existe un evento con el slug «{data.slug}»")
        event_id = await self._repo.create_event(
            {**data.model_dump(), "organization_id": organization_id}
        )
        rubric_id = await self._rubrics.create_rubric_for_event(event_id, default_rubric())
        await self._repo.update_event(event_id, {"default_rubric_id": rubric_id})
        return await self.get_event(organization_id, event_id)

    async def update_event(
        self, organization_id: UUID, event_id: UUID, data: EventUpdate
    ) -> EventOut:
        event = await self._require_event(organization_id, event_id)
        _ensure_not_closed(event["status"])
        values = data.model_dump(exclude_unset=True)
        for required in ("slug", "name", "brand", "timezone", "starts_on", "ends_on", "status"):
            if required in values and values[required] is None:
                raise DomainError(ErrorCode.VALIDATION_ERROR, f"El campo {required} es obligatorio")

        starts_on = values.get("starts_on", event["starts_on"])
        ends_on = values.get("ends_on", event["ends_on"])
        if ends_on < starts_on:
            raise DomainError(
                ErrorCode.VALIDATION_ERROR, "ends_on debe ser igual o posterior a starts_on"
            )
        if "slug" in values and await self._repo.slug_exists(values["slug"], event_id):
            raise DomainError(
                ErrorCode.CONFLICT, f"Ya existe un evento con el slug «{values['slug']}»"
            )
        rubric_id = values.get("default_rubric_id")
        if rubric_id is not None and not await self._repo.rubric_belongs_to_event(
            rubric_id, event_id
        ):
            raise NotFoundError("La rúbrica no pertenece a este evento")

        await self._repo.update_event(event_id, values)
        return await self.get_event(organization_id, event_id)

    async def delete_event(self, organization_id: UUID, event_id: UUID) -> None:
        event = await self._require_event(organization_id, event_id)
        if event["status"] != "draft":
            raise DomainError(ErrorCode.CONFLICT, "Solo se pueden borrar eventos en borrador")
        await self._repo.delete_event(event_id)

    async def upload_logo(
        self, organization_id: UUID, event_id: UUID, content: bytes, content_type: str | None
    ) -> EventOut:
        event = await self._require_event(organization_id, event_id)
        _ensure_not_closed(event["status"])
        extension = LOGO_CONTENT_TYPES.get((content_type or "").lower())
        if extension is None:
            raise DomainError(ErrorCode.VALIDATION_ERROR, "El logo debe ser PNG, SVG o WebP")
        if len(content) > LOGO_MAX_BYTES:
            raise DomainError(ErrorCode.VALIDATION_ERROR, "El logo no puede superar 2 MB")
        if not content:
            raise DomainError(ErrorCode.VALIDATION_ERROR, "El archivo está vacío")

        # Nombre único para evitar cachés del CDN con el logo anterior.
        path = f"{event_id}/logo-{uuid.uuid4().hex[:12]}.{extension}"
        await self._storage.upload(EVENT_LOGOS_BUCKET, path, content, str(content_type))
        await self._repo.update_event(event_id, {"logo_path": path})
        return await self.get_event(organization_id, event_id)

    # ------------------------------------------------------------ comités

    async def _require_committee(self, organization_id: UUID, committee_id: UUID) -> dict[str, Any]:
        committee = await self._repo.get_committee(committee_id, organization_id)
        if committee is None:
            raise NotFoundError("Comité no encontrado")
        return committee

    @staticmethod
    def _committee_out(row: dict[str, Any]) -> CommitteeOut:
        return CommitteeOut(**{k: row[k] for k in CommitteeOut.model_fields})

    async def list_committees(
        self, organization_id: UUID, event_id: UUID, page: PageParams
    ) -> Page[CommitteeOut]:
        await self._require_event(organization_id, event_id)
        rows, total = await self._repo.list_committees(event_id, page.limit, page.offset)
        return Page[CommitteeOut](items=[self._committee_out(r) for r in rows], total=total)

    async def get_committee(self, organization_id: UUID, committee_id: UUID) -> CommitteeOut:
        return self._committee_out(await self._require_committee(organization_id, committee_id))

    async def create_committee(
        self, organization_id: UUID, event_id: UUID, data: CommitteeCreate
    ) -> CommitteeOut:
        event = await self._require_event(organization_id, event_id)
        _ensure_not_closed(event["status"])
        if await self._repo.committee_slug_exists(event_id, data.slug):
            raise DomainError(ErrorCode.CONFLICT, f"Ya existe un comité con el slug «{data.slug}»")
        if data.rubric_id is not None and not await self._repo.rubric_belongs_to_event(
            data.rubric_id, event_id
        ):
            raise NotFoundError("La rúbrica no pertenece a este evento")

        values = data.model_dump()
        values["award_quotas"] = _quotas(data.type, data.award_quotas)
        committee_id = await self._repo.create_committee({**values, "event_id": event_id})
        await self._repo.create_sessions(committee_id, range(1, data.sessions_count + 1))
        return await self.get_committee(organization_id, committee_id)

    async def update_committee(
        self, organization_id: UUID, committee_id: UUID, data: CommitteeUpdate
    ) -> CommitteeOut:
        committee = await self._require_committee(organization_id, committee_id)
        _ensure_not_closed(committee["event_status"])
        values = data.model_dump(exclude_unset=True)
        for required in ("name", "acronym", "slug", "type", "delegation_mode", "sessions_count"):
            if required in values and values[required] is None:
                raise DomainError(ErrorCode.VALIDATION_ERROR, f"El campo {required} es obligatorio")
        event_id = committee["event_id"]

        if "slug" in values and await self._repo.committee_slug_exists(
            event_id, values["slug"], committee_id
        ):
            raise DomainError(
                ErrorCode.CONFLICT, f"Ya existe un comité con el slug «{values['slug']}»"
            )
        if values.get("rubric_id") is not None and not await self._repo.rubric_belongs_to_event(
            values["rubric_id"], event_id
        ):
            raise NotFoundError("La rúbrica no pertenece a este evento")
        if values.get("delegation_mode") == "single" and (
            await self._repo.max_delegates_in_committee(committee_id) > 1
        ):
            raise _delegates_limit_error("single")
        if "award_quotas" in values or "type" in values:
            # Los cupos que no se indiquen toman el valor por defecto del tipo (nuevo o actual).
            committee_type = values.get("type", committee["type"])
            values["award_quotas"] = _quotas(committee_type, values.get("award_quotas"))

        new_count = values.get("sessions_count")
        if new_count is not None:
            numbers = await self._repo.session_numbers(committee_id)
            if new_count < len(numbers):
                if await self._repo.sessions_with_scores_above(committee_id, new_count):
                    raise DomainError(
                        ErrorCode.CONFLICT,
                        "No se pueden quitar sesiones que ya tienen calificaciones",
                    )
                await self._repo.delete_sessions_above(committee_id, new_count)
            missing = [n for n in range(1, new_count + 1) if n not in numbers]
            await self._repo.create_sessions(committee_id, missing)

        await self._repo.update_committee(committee_id, values)
        return await self.get_committee(organization_id, committee_id)

    async def delete_committee(self, organization_id: UUID, committee_id: UUID) -> None:
        committee = await self._require_committee(organization_id, committee_id)
        _ensure_not_closed(committee["event_status"])
        await self._repo.delete_committee(committee_id)

    # ------------------------------------------------------------ delegaciones

    async def _delegations_out(self, rows: list[dict[str, Any]]) -> list[DelegationOut]:
        delegate_rows = await self._repo.list_delegates([r["id"] for r in rows])
        by_delegation: dict[UUID, list[DelegateOut]] = {r["id"]: [] for r in rows}
        for d in delegate_rows:
            by_delegation[d["delegation_id"]].append(
                DelegateOut(**{k: d[k] for k in DelegateOut.model_fields})
            )
        return [
            DelegationOut(
                **{k: r[k] for k in DelegationOut.model_fields if k != "delegates"},
                delegates=by_delegation[r["id"]],
            )
            for r in rows
        ]

    async def _require_delegation(
        self, organization_id: UUID, delegation_id: UUID
    ) -> dict[str, Any]:
        delegation = await self._repo.get_delegation(delegation_id, organization_id)
        if delegation is None:
            raise NotFoundError("Delegación no encontrada")
        return delegation

    async def _delegation_out(self, organization_id: UUID, delegation_id: UUID) -> DelegationOut:
        row = await self._require_delegation(organization_id, delegation_id)
        return (await self._delegations_out([row]))[0]

    async def list_delegations(
        self, organization_id: UUID, committee_id: UUID, page: PageParams
    ) -> Page[DelegationOut]:
        await self._require_committee(organization_id, committee_id)
        rows, total = await self._repo.list_delegations(committee_id, page.limit, page.offset)
        return Page[DelegationOut](items=await self._delegations_out(rows), total=total)

    async def _insert_delegation(
        self,
        committee_id: UUID,
        *,
        country_code: str | None,
        character_name: str | None,
        institution: str | None,
        delegate_names: list[DelegateIn],
    ) -> UUID:
        delegation_id = await self._repo.create_delegation(
            {
                "committee_id": committee_id,
                "country_code": country_code,
                "character_name": character_name,
                "institution": institution,
            }
        )
        for delegate in delegate_names:
            await self._repo.create_delegate(
                {
                    "delegation_id": delegation_id,
                    "full_name": delegate.full_name.strip(),
                    "institution": delegate.institution or institution,
                }
            )
        return delegation_id

    async def create_delegation(
        self, organization_id: UUID, committee_id: UUID, data: DelegationCreate
    ) -> DelegationOut:
        committee = await self._require_committee(organization_id, committee_id)
        _ensure_not_closed(committee["event_status"])
        if len(data.delegates) > MAX_DELEGATES[committee["delegation_mode"]]:
            raise _delegates_limit_error(committee["delegation_mode"])
        if data.country_code and await self._repo.country_taken(committee_id, data.country_code):
            raise DomainError(
                ErrorCode.CONFLICT, f"La delegación {data.country_code} ya existe en el comité"
            )
        delegation_id = await self._insert_delegation(
            committee_id,
            country_code=data.country_code,
            character_name=data.character_name,
            institution=data.institution,
            delegate_names=data.delegates,
        )
        return await self._delegation_out(organization_id, delegation_id)

    async def update_delegation(
        self, organization_id: UUID, delegation_id: UUID, data: DelegationUpdate
    ) -> DelegationOut:
        delegation = await self._require_delegation(organization_id, delegation_id)
        _ensure_not_closed(delegation["event_status"])
        values = data.model_dump(exclude_unset=True)
        country = values.get("country_code", delegation["country_code"])
        character = values.get("character_name", delegation["character_name"])
        if (country is None) == (character is None):
            raise DomainError(
                ErrorCode.VALIDATION_ERROR, "Indica exactamente uno: country_code o character_name"
            )
        if (
            "country_code" in values
            and country is not None
            and await self._repo.country_taken(delegation["committee_id"], country, delegation_id)
        ):
            raise DomainError(ErrorCode.CONFLICT, f"La delegación {country} ya existe en el comité")
        await self._repo.update_delegation(delegation_id, values)
        return await self._delegation_out(organization_id, delegation_id)

    async def delete_delegation(self, organization_id: UUID, delegation_id: UUID) -> None:
        delegation = await self._require_delegation(organization_id, delegation_id)
        _ensure_not_closed(delegation["event_status"])
        await self._repo.delete_delegation(delegation_id)

    async def import_delegations(
        self, organization_id: UUID, committee_id: UUID, content: bytes
    ) -> ImportResult:
        committee = await self._require_committee(organization_id, committee_id)
        _ensure_not_closed(committee["event_status"])
        parsed = parse_delegations_csv(content, committee["delegation_mode"])
        existing = await self._repo.country_codes_in_committee(committee_id)

        created = skipped = 0
        errors: list[ImportRowError] = []
        for row in parsed:
            if isinstance(row, CsvRowError):
                errors.append(ImportRowError(row=row.line, message=row.message))
                continue
            if row.country_code is not None and row.country_code in existing:
                skipped += 1
                continue
            await self._insert_delegation(
                committee_id,
                country_code=row.country_code,
                character_name=row.character_name,
                institution=row.institution,
                delegate_names=[DelegateIn(full_name=name) for name in row.delegates],
            )
            if row.country_code is not None:
                existing.add(row.country_code)
            created += 1
        return ImportResult(created=created, skipped=skipped, errors=errors)

    # ------------------------------------------------------------ delegados

    async def add_delegate(
        self, organization_id: UUID, delegation_id: UUID, data: DelegateIn
    ) -> DelegateOut:
        delegation = await self._require_delegation(organization_id, delegation_id)
        _ensure_not_closed(delegation["event_status"])
        mode: DelegationMode = delegation["delegation_mode"]
        if await self._repo.count_delegates(delegation_id) >= MAX_DELEGATES[mode]:
            raise _delegates_limit_error(mode)
        delegate_id = await self._repo.create_delegate(
            {
                "delegation_id": delegation_id,
                "full_name": data.full_name.strip(),
                "institution": data.institution or delegation["institution"],
            }
        )
        return await self._delegate_out(organization_id, delegate_id)

    async def _require_delegate(self, organization_id: UUID, delegate_id: UUID) -> dict[str, Any]:
        delegate = await self._repo.get_delegate(delegate_id, organization_id)
        if delegate is None:
            raise NotFoundError("Delegado no encontrado")
        return delegate

    async def _delegate_out(self, organization_id: UUID, delegate_id: UUID) -> DelegateOut:
        row = await self._require_delegate(organization_id, delegate_id)
        return DelegateOut(**{k: row[k] for k in DelegateOut.model_fields})

    async def update_delegate(
        self, organization_id: UUID, delegate_id: UUID, data: DelegateUpdate
    ) -> DelegateOut:
        delegate = await self._require_delegate(organization_id, delegate_id)
        _ensure_not_closed(delegate["event_status"])
        values = data.model_dump(exclude_unset=True)
        if "full_name" in values:
            if values["full_name"] is None:
                raise DomainError(ErrorCode.VALIDATION_ERROR, "El campo full_name es obligatorio")
            values["full_name"] = values["full_name"].strip()
        await self._repo.update_delegate(delegate_id, values)
        return await self._delegate_out(organization_id, delegate_id)

    async def delete_delegate(self, organization_id: UUID, delegate_id: UUID) -> None:
        delegate = await self._require_delegate(organization_id, delegate_id)
        _ensure_not_closed(delegate["event_status"])
        await self._repo.delete_delegate(delegate_id)
