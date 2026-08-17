"""Application service for Service API end-user queries."""

from typing import Protocol

from machinery.context import ServiceApiRequestContext
from services.entities.end_user_entities import EndUserRecord


class EndUserNotFoundError(LookupError):
    """Raised when an end user is not visible in the admitted app scope."""


class EndUserQuery(Protocol):
    def find_by_id(self, *, tenant_id: str, app_id: str, end_user_id: str) -> EndUserRecord | None: ...


class EndUserQueryService:
    def __init__(self, *, end_users: EndUserQuery) -> None:
        self._end_users = end_users

    def get_by_id(self, context: ServiceApiRequestContext, end_user_id: str) -> EndUserRecord:
        end_user = self._end_users.find_by_id(
            tenant_id=context.tenant_id,
            app_id=context.app_id,
            end_user_id=end_user_id,
        )
        if end_user is None:
            raise EndUserNotFoundError(end_user_id)
        return end_user
