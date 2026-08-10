from __future__ import annotations

from datetime import datetime
from types import TracebackType
from unittest.mock import Mock

import pytest

from machinery.context import RequestContext
from services.account_errors import AccountNotFoundError, CurrentAccountPasswordIncorrectError
from services.account_password_service import AccountPasswordService
from services.account_ports import AccountPasswordHasher, AccountRepository
from services.entities.account_entities import AccountCredentials, AccountPasswordDigest, AccountSnapshot


def _context() -> RequestContext:
    return RequestContext(
        request_id="request-1",
        trace_id="trace-1",
        account_id="account-1",
        active_workspace_id="workspace-1",
    )


def _account() -> AccountSnapshot:
    return AccountSnapshot(
        id="account-1",
        name="Account",
        email="account@example.com",
        avatar=None,
        is_password_set=True,
        interface_language="en-US",
        interface_theme="light",
        timezone="UTC",
        last_login_at=None,
        last_login_ip=None,
        status="active",
        initialized_at=None,
        created_at=datetime(2026, 1, 1),
    )


class _FakeAccountUnitOfWork:
    def __init__(self, accounts: Mock) -> None:
        self.accounts: AccountRepository = accounts
        self.commit_count = 0

    def __enter__(self) -> _FakeAccountUnitOfWork:
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


def test_change_verifies_current_password_and_commits_new_digest() -> None:
    accounts = Mock(spec=AccountRepository)
    accounts.get_credentials.return_value = AccountCredentials(password_hash="old-hash", password_salt="old-salt")
    accounts.update_password.return_value = _account()
    passwords = Mock(spec=AccountPasswordHasher)
    passwords.verify.return_value = True
    digest = AccountPasswordDigest(password_hash="new-hash", password_salt="new-salt")
    passwords.hash.return_value = digest
    unit_of_work = _FakeAccountUnitOfWork(accounts)
    service = AccountPasswordService(unit_of_work=lambda: unit_of_work, passwords=passwords)

    result = service.change(_context(), current_password="old-password", new_password="new-password1")

    assert result == _account()
    passwords.verify.assert_called_once_with(
        "old-password",
        password_hash="old-hash",
        password_salt="old-salt",
    )
    passwords.hash.assert_called_once_with("new-password1")
    accounts.update_password.assert_called_once_with("account-1", digest)
    assert unit_of_work.commit_count == 1


def test_change_rejects_incorrect_current_password_without_hashing_or_commit() -> None:
    accounts = Mock(spec=AccountRepository)
    accounts.get_credentials.return_value = AccountCredentials(password_hash="old-hash", password_salt="old-salt")
    passwords = Mock(spec=AccountPasswordHasher)
    passwords.verify.return_value = False
    unit_of_work = _FakeAccountUnitOfWork(accounts)
    service = AccountPasswordService(unit_of_work=lambda: unit_of_work, passwords=passwords)

    with pytest.raises(CurrentAccountPasswordIncorrectError):
        service.change(_context(), current_password="wrong", new_password="new-password1")

    passwords.hash.assert_not_called()
    accounts.update_password.assert_not_called()
    assert unit_of_work.commit_count == 0


def test_change_does_not_verify_current_password_when_account_has_no_password() -> None:
    accounts = Mock(spec=AccountRepository)
    accounts.get_credentials.return_value = AccountCredentials(password_hash=None, password_salt=None)
    accounts.update_password.return_value = _account()
    passwords = Mock(spec=AccountPasswordHasher)
    passwords.hash.return_value = AccountPasswordDigest(password_hash="new-hash", password_salt="new-salt")
    unit_of_work = _FakeAccountUnitOfWork(accounts)
    service = AccountPasswordService(unit_of_work=lambda: unit_of_work, passwords=passwords)

    service.change(_context(), current_password="", new_password="new-password1")

    passwords.verify.assert_not_called()
    assert unit_of_work.commit_count == 1


def test_change_reports_missing_account() -> None:
    accounts = Mock(spec=AccountRepository)
    accounts.get_credentials.return_value = None
    passwords = Mock(spec=AccountPasswordHasher)
    service = AccountPasswordService(
        unit_of_work=lambda: _FakeAccountUnitOfWork(accounts),
        passwords=passwords,
    )

    with pytest.raises(AccountNotFoundError):
        service.change(_context(), current_password="old", new_password="new-password1")

    passwords.hash.assert_not_called()
