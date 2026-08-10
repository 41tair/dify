from __future__ import annotations

from datetime import UTC, datetime
from types import TracebackType
from unittest.mock import Mock

import pytest

from machinery.context import RequestContext
from services.account_education_service import AccountEducationGateway, AccountEducationService
from services.account_errors import EducationDiscountPausedError
from services.account_ports import AccountRepository
from services.entities.account_entities import (
    AccountEducationAutocomplete,
    AccountEducationStatus,
    AccountEducationVerification,
    AccountSnapshot,
)


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
        name="Student",
        email="student@example.edu",
        avatar=None,
        is_password_set=True,
        interface_language="en-US",
        interface_theme="light",
        timezone="UTC",
        last_login_at=None,
        last_login_ip=None,
        status="active",
        initialized_at=datetime(2026, 1, 1),
        created_at=datetime(2026, 1, 1),
    )


class _FakeAccountUnitOfWork:
    def __init__(self, accounts: Mock) -> None:
        self.accounts: AccountRepository = accounts
        self.active = False

    def __enter__(self) -> _FakeAccountUnitOfWork:
        self.active = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.active = False

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


def test_verify_closes_account_session_before_billing_gateway_call() -> None:
    accounts = Mock(spec=AccountRepository)
    accounts.get.return_value = _account()
    unit_of_work = _FakeAccountUnitOfWork(accounts)
    education = Mock(spec=AccountEducationGateway)
    education.verify.side_effect = lambda **_: verify_after_session_closed(unit_of_work)
    service = AccountEducationService(unit_of_work=lambda: unit_of_work, education=education)

    result = service.verify(_context())

    assert result == AccountEducationVerification(token="education-token")
    education.verify.assert_called_once_with(account_id="account-1", email="student@example.edu")


def verify_after_session_closed(unit_of_work: _FakeAccountUnitOfWork) -> AccountEducationVerification:
    assert unit_of_work.active is False
    return AccountEducationVerification(token="education-token")


def test_status_and_autocomplete_delegate_framework_neutral_contracts() -> None:
    accounts = Mock(spec=AccountRepository)
    education = Mock(spec=AccountEducationGateway)
    status = AccountEducationStatus(
        result=True,
        is_student=True,
        expire_at=datetime(2027, 1, 1, tzinfo=UTC),
        allow_refresh=False,
    )
    autocomplete = AccountEducationAutocomplete(data=("Example University",), curr_page=0, has_next=False)
    education.status.return_value = status
    education.autocomplete.return_value = autocomplete
    service = AccountEducationService(
        unit_of_work=lambda: _FakeAccountUnitOfWork(accounts),
        education=education,
    )

    assert service.status(_context()) == status
    assert service.autocomplete(_context(), keywords="Example", page=0, limit=20) == autocomplete
    education.status.assert_called_once_with("account-1")
    education.autocomplete.assert_called_once_with(keywords="Example", page=0, limit=20)


def test_activate_exposes_paused_policy_as_application_error() -> None:
    service = AccountEducationService(
        unit_of_work=Mock(),
        education=Mock(spec=AccountEducationGateway),
    )

    with pytest.raises(EducationDiscountPausedError):
        service.activate(_context())
