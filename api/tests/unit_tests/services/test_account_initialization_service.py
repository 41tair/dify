from __future__ import annotations

from datetime import datetime
from types import TracebackType
from unittest.mock import Mock

import pytest

from machinery.context import RequestContext
from services.account_errors import (
    AccountAlreadyInitializedError,
    InvalidInvitationCodeError,
    MissingInvitationCodeError,
)
from services.account_initialization_service import AccountInitializationService
from services.account_ports import AccountInvitationRepository, AccountRepository
from services.entities.account_entities import AccountInitialization, AccountSnapshot


def _context() -> RequestContext:
    return RequestContext(
        request_id="request-1",
        trace_id="trace-1",
        account_id="account-1",
        active_workspace_id="workspace-1",
    )


def _account(*, status: str = "uninitialized") -> AccountSnapshot:
    return AccountSnapshot(
        id="account-1",
        name="Account",
        email="account@example.com",
        avatar=None,
        is_password_set=False,
        interface_language="en-US",
        interface_theme="light",
        timezone="UTC",
        last_login_at=None,
        last_login_ip=None,
        status=status,
        initialized_at=None,
        created_at=datetime(2026, 1, 1),
    )


class _FakeAccountInitializationUnitOfWork:
    def __init__(self, accounts: Mock, invitations: Mock) -> None:
        self.accounts: AccountRepository = accounts
        self.invitations: AccountInvitationRepository = invitations
        self.commit_count = 0

    def __enter__(self) -> _FakeAccountInitializationUnitOfWork:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        return None


def test_cloud_initialization_consumes_invitation_and_updates_account_atomically() -> None:
    initialized_at = datetime(2026, 8, 10, 12, 0)
    accounts = Mock(spec=AccountRepository)
    accounts.get.return_value = _account()
    accounts.initialize.return_value = _account(status="active")
    invitations = Mock(spec=AccountInvitationRepository)
    invitations.consume.return_value = True
    unit_of_work = _FakeAccountInitializationUnitOfWork(accounts, invitations)
    service = AccountInitializationService(
        unit_of_work=lambda: unit_of_work,
        invitation_required=True,
        now=lambda: initialized_at,
    )

    result = service.initialize(
        _context(),
        interface_language="zh-Hans",
        timezone="Asia/Shanghai",
        invitation_code="invite-1",
    )

    assert result.status == "active"
    invitations.consume.assert_called_once_with(
        code="invite-1",
        account_id="account-1",
        workspace_id="workspace-1",
        used_at=initialized_at,
    )
    accounts.initialize.assert_called_once_with(
        "account-1",
        AccountInitialization(
            interface_language="zh-Hans",
            interface_theme="light",
            timezone="Asia/Shanghai",
            initialized_at=initialized_at,
        ),
    )
    assert unit_of_work.commit_count == 1


def test_cloud_initialization_rejects_missing_or_invalid_invitation_without_commit() -> None:
    accounts = Mock(spec=AccountRepository)
    accounts.get.return_value = _account()
    invitations = Mock(spec=AccountInvitationRepository)
    unit_of_work = _FakeAccountInitializationUnitOfWork(accounts, invitations)
    service = AccountInitializationService(
        unit_of_work=lambda: unit_of_work,
        invitation_required=True,
        now=lambda: datetime(2026, 8, 10),
    )

    with pytest.raises(MissingInvitationCodeError):
        service.initialize(_context(), interface_language="en-US", timezone="UTC", invitation_code=None)

    invitations.consume.return_value = False
    with pytest.raises(InvalidInvitationCodeError):
        service.initialize(_context(), interface_language="en-US", timezone="UTC", invitation_code="used")

    accounts.initialize.assert_not_called()
    assert unit_of_work.commit_count == 0


def test_initialization_rejects_an_active_account_before_consuming_invitation() -> None:
    accounts = Mock(spec=AccountRepository)
    accounts.get.return_value = _account(status="active")
    invitations = Mock(spec=AccountInvitationRepository)
    service = AccountInitializationService(
        unit_of_work=lambda: _FakeAccountInitializationUnitOfWork(accounts, invitations),
        invitation_required=True,
        now=lambda: datetime(2026, 8, 10),
    )

    with pytest.raises(AccountAlreadyInitializedError):
        service.initialize(_context(), interface_language="en-US", timezone="UTC", invitation_code="invite")

    invitations.consume.assert_not_called()
