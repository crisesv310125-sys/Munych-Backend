from typing import Annotated

from fastapi import Depends, Request

from munych_api.modules.judging.repository import JudgingRepository
from munych_api.modules.judging.service import JudgingService
from munych_api.shared.database import DbSession
from munych_api.shared.supabase import ObjectStorage


def get_object_storage(request: Request) -> ObjectStorage:
    storage: ObjectStorage = request.app.state.supabase
    return storage


def get_judging_service(
    session: DbSession, storage: Annotated[ObjectStorage, Depends(get_object_storage)]
) -> JudgingService:
    return JudgingService(JudgingRepository(session), storage)


JudgingServiceDep = Annotated[JudgingService, Depends(get_judging_service)]
