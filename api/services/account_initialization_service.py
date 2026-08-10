"""Application service for initializing a newly admitted account."""

from collections.abc import Callable
from datetime import datetime

from machinery.context import RequestContext
from services.account_errors import (
    AccountAlreadyInitializedError,
    AccountNotFoundError,
    InvalidInvitationCodeError,
    MissingInvitationCodeError,
)
from services.account_ports import AccountInitializationUnitOfWork, UnitOfWorkFactory
from services.entities.account_entities import AccountInitialization, AccountSnapshot


class AccountInitializationService:
    def __init__(
        self,
        *,
        unit_of_work: UnitOfWorkFactory[AccountInitializationUnitOfWork],
        invitation_required: bool,
        now: Callable[[], datetime],
    ) -> None:
        self._unit_of_work = unit_of_work
        self._invitation_required = invitation_required
        self._now = now

    def initialize(
        self,
        context: RequestContext,
        *,
        interface_language: str,
        timezone: str,
        invitation_code: str | None,
    ) -> AccountSnapshot:
        initialized_at = self._now()
        with self._unit_of_work() as unit_of_work:
            account = unit_of_work.accounts.get(context.account_id)
            if account is None:
                raise AccountNotFoundError
            if account.status == "active":
                raise AccountAlreadyInitializedError

            if self._invitation_required:
                if invitation_code is None:
                    raise MissingInvitationCodeError("invitation_code is required")
                workspace_id = context.active_workspace_id
                if workspace_id is None:
                    raise RuntimeError("Console account admission did not resolve an active workspace")
                if not unit_of_work.invitations.consume(
                    code=invitation_code,
                    account_id=context.account_id,
                    workspace_id=workspace_id,
                    used_at=initialized_at,
                ):
                    raise InvalidInvitationCodeError

            initialized_account = unit_of_work.accounts.initialize(
                context.account_id,
                AccountInitialization(
                    interface_language=interface_language,
                    interface_theme="light",
                    timezone=timezone,
                    initialized_at=initialized_at,
                ),
            )
            if initialized_account is None:
                raise AccountNotFoundError
            unit_of_work.commit()
        return initialized_account
