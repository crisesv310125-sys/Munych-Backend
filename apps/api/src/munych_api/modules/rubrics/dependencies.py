from typing import Annotated

from fastapi import Depends

from munych_api.modules.rubrics.repository import RubricsRepository
from munych_api.modules.rubrics.service import RubricsService
from munych_api.shared.database import DbSession


def get_rubrics_service(session: DbSession) -> RubricsService:
    return RubricsService(RubricsRepository(session))


RubricsServiceDep = Annotated[RubricsService, Depends(get_rubrics_service)]
