"""Application service for account education-discount use cases."""

from typing import Protocol

from machinery.context import RequestContext
from services.account_errors import AccountNotFoundError, EducationDiscountPausedError
from services.account_ports import AccountRepositoryUnitOfWork, UnitOfWorkFactory
from services.entities.account_entities import (
    AccountEducationAutocomplete,
    AccountEducationStatus,
    AccountEducationVerification,
)


class AccountEducationGateway(Protocol):
    def verify(self, *, account_id: str, email: str) -> AccountEducationVerification: ...

    def status(self, account_id: str) -> AccountEducationStatus: ...

    def autocomplete(self, *, keywords: str, page: int, limit: int) -> AccountEducationAutocomplete: ...


class AccountEducationService:
    def __init__(
        self,
        *,
        unit_of_work: UnitOfWorkFactory[AccountRepositoryUnitOfWork],
        education: AccountEducationGateway,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._education = education

    def verify(self, context: RequestContext) -> AccountEducationVerification:
        with self._unit_of_work() as unit_of_work:
            account = unit_of_work.accounts.get(context.account_id)
        if account is None:
            raise AccountNotFoundError
        return self._education.verify(account_id=account.id, email=account.email)

    def activate(self, context: RequestContext) -> None:
        raise EducationDiscountPausedError

    def status(self, context: RequestContext) -> AccountEducationStatus:
        return self._education.status(context.account_id)

    def autocomplete(
        self,
        context: RequestContext,
        *,
        keywords: str,
        page: int,
        limit: int,
    ) -> AccountEducationAutocomplete:
        return self._education.autocomplete(keywords=keywords, page=page, limit=limit)
