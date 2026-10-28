from typing import Annotated

from fastapi import Depends, Request

from munych_api.modules.events.repository import EventsRepository
from munych_api.modules.events.service import EventsService
from munych_api.modules.rubrics.dependencies import RubricsServiceDep
from munych_api.shared.database import DbSession
from munych_api.shared.supabase import ObjectStorage


def get_object_storage(request: Request) -> ObjectStorage:
    storage: ObjectStorage = request.app.state.supabase
    return storage


def get_events_service(
    session: DbSession,
    rubrics: RubricsServiceDep,
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
) -> EventsService:
    return EventsService(EventsRepository(session), rubrics, storage)


EventsServiceDep = Annotated[EventsService, Depends(get_events_service)]
