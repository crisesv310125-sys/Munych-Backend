"""Paginación común: `?limit=&offset=` → `{ items, total }`."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query
from pydantic import BaseModel


class Page[T](BaseModel):
    items: list[T]
    total: int


@dataclass(frozen=True, slots=True)
class PageParams:
    limit: int
    offset: int


def _page_params(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PageParams:
    return PageParams(limit=limit, offset=offset)


Pagination = Annotated[PageParams, Depends(_page_params)]
