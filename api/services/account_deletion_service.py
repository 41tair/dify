"""Application service for the current account deletion lifecycle."""

import logging

from machinery.context import RequestContext
from services.account_errors import AccountNotFoundError, InvalidAccountDeletionVerificationError
from services.account_ports import (
    AccountDeletionScheduler,
    AccountDeletionSyncGateway,
    AccountDeletionVerificationGateway,
    AccountDeletionVerificationNotifier,
    AccountRepositoryUnitOfWork,
    AccountWorkspaceMembershipQuery,
    UnitOfWorkFactory,
)

logger = logging.getLogger(__name__)


class AccountDeletionService:
    def __init__(
        self,
        *,
        unit_of_work: UnitOfWorkFactory[AccountRepositoryUnitOfWork],
        memberships: AccountWorkspaceMembershipQuery,
        verification: AccountDeletionVerificationGateway,
        notifications: AccountDeletionVerificationNotifier,
        synchronization: AccountDeletionSyncGateway,
        scheduler: AccountDeletionScheduler,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._memberships = memberships
        self._verification = verification
        self._notifications = notifications
        self._synchronization = synchronization
        self._scheduler = scheduler

    def issue_verification(self, context: RequestContext) -> str:
        with self._unit_of_work() as unit_of_work:
            account = unit_of_work.accounts.get(context.account_id)
        if account is None:
            raise AccountNotFoundError

        challenge = self._verification.create(account_id=account.id, email=account.email)
        self._notifications.send(email=account.email, code=challenge.code)
        return challenge.token

    def request_deletion(self, context: RequestContext, *, token: str, code: str) -> None:
        if not self._verification.verify(account_id=context.account_id, token=token, code=code):
            raise InvalidAccountDeletionVerificationError

        workspace_ids = tuple(self._memberships.list_ids_for_account(context.account_id))
        if not self._synchronization.sync(account_id=context.account_id, workspace_ids=workspace_ids):
            logger.warning(
                "Enterprise account deletion sync failed for account %s; proceeding with local deletion.",
                context.account_id,
            )
        self._scheduler.schedule(context.account_id)
