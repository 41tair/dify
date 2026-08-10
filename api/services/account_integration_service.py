"""Application service for listing current account integrations."""

from collections.abc import Sequence

from machinery.context import RequestContext
from services.account_ports import AccountIntegrationUnitOfWork, UnitOfWorkFactory
from services.entities.account_entities import AccountIntegrationStatus


class AccountIntegrationService:
    def __init__(
        self,
        *,
        unit_of_work: UnitOfWorkFactory[AccountIntegrationUnitOfWork],
        providers: Sequence[str] = ("github", "google"),
    ) -> None:
        self._unit_of_work = unit_of_work
        self._providers = tuple(providers)

    def list(self, context: RequestContext) -> list[AccountIntegrationStatus]:
        with self._unit_of_work() as unit_of_work:
            integrations = unit_of_work.integrations.list_for_account(context.account_id)

        integrations_by_provider = {integration.provider: integration for integration in integrations}
        statuses: list[AccountIntegrationStatus] = []
        for provider in self._providers:
            integration = integrations_by_provider.get(provider)
            statuses.append(
                AccountIntegrationStatus(
                    provider=provider,
                    created_at=integration.created_at if integration else None,
                    is_bound=integration is not None,
                )
            )
        return statuses
