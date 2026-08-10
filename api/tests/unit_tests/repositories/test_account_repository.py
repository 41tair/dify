from datetime import datetime

import pytest
from sqlalchemy.orm import Session, sessionmaker

from models.account import Account, AccountIntegrate, AccountStatus, InvitationCode, InvitationCodeStatus
from repositories.account_unit_of_work import SQLAlchemyAccountUnitOfWorkFactory
from services.entities.account_entities import AccountInitialization, AccountPasswordDigest, AccountProfileChanges


def _persist_account(session: Session) -> Account:
    account = Account(name="Original", email="account@example.com")
    account.id = "account-1"
    account.interface_language = "en-US"
    account.interface_theme = "light"
    account.timezone = "UTC"
    session.add(account)
    session.commit()
    return account


def test_unit_of_work_updates_multiple_profile_fields_atomically(
    sqlite_session: Session,
    sqlite_session_factory: sessionmaker[Session],
) -> None:
    _persist_account(sqlite_session)
    factory = SQLAlchemyAccountUnitOfWorkFactory(sqlite_session_factory)

    with factory() as unit_of_work:
        result = unit_of_work.accounts.update_profile(
            "account-1",
            AccountProfileChanges(
                name="Updated",
                avatar="avatar-file",
                interface_language="zh-Hans",
                interface_theme="dark",
                timezone="Asia/Shanghai",
            ),
        )
        unit_of_work.commit()

    assert result is not None
    assert result.name == "Updated"
    sqlite_session.expire_all()
    persisted = sqlite_session.get(Account, "account-1")
    assert persisted is not None
    assert persisted.name == "Updated"
    assert persisted.avatar == "avatar-file"
    assert persisted.interface_language == "zh-Hans"
    assert persisted.interface_theme == "dark"
    assert persisted.timezone == "Asia/Shanghai"


def test_unit_of_work_rolls_back_uncommitted_profile_changes(
    sqlite_session: Session,
    sqlite_session_factory: sessionmaker[Session],
) -> None:
    _persist_account(sqlite_session)
    factory = SQLAlchemyAccountUnitOfWorkFactory(sqlite_session_factory)

    def update_then_abort() -> None:
        with factory() as unit_of_work:
            unit_of_work.accounts.update_profile(
                "account-1",
                AccountProfileChanges(name="Should Roll Back"),
            )
            raise RuntimeError("abort update")

    with pytest.raises(RuntimeError, match="abort update"):
        update_then_abort()

    sqlite_session.expire_all()
    persisted = sqlite_session.get(Account, "account-1")
    assert persisted is not None
    assert persisted.name == "Original"


def test_unit_of_work_updates_password_through_account_repository(
    sqlite_session: Session,
    sqlite_session_factory: sessionmaker[Session],
) -> None:
    _persist_account(sqlite_session)
    factory = SQLAlchemyAccountUnitOfWorkFactory(sqlite_session_factory)
    digest = AccountPasswordDigest(password_hash="new-hash", password_salt="new-salt")

    with factory() as unit_of_work:
        credentials = unit_of_work.accounts.get_credentials("account-1")
        result = unit_of_work.accounts.update_password("account-1", digest)
        unit_of_work.commit()

    assert credentials is not None
    assert credentials.password_hash is None
    assert result is not None
    assert result.is_password_set is True
    sqlite_session.expire_all()
    persisted = sqlite_session.get(Account, "account-1")
    assert persisted is not None
    assert persisted.password == "new-hash"
    assert persisted.password_salt == "new-salt"


def test_unit_of_work_exposes_account_integrations_from_the_same_short_lived_session(
    sqlite_session: Session,
    sqlite_session_factory: sessionmaker[Session],
) -> None:
    _persist_account(sqlite_session)
    sqlite_session.add(
        AccountIntegrate(
            account_id="account-1",
            provider="github",
            open_id="github-user",
            encrypted_token="encrypted-token",
        )
    )
    sqlite_session.commit()
    factory = SQLAlchemyAccountUnitOfWorkFactory(sqlite_session_factory)

    with factory() as unit_of_work:
        integrations = unit_of_work.integrations.list_for_account("account-1")

    assert len(integrations) == 1
    assert integrations[0].provider == "github"


def test_unit_of_work_initializes_account_and_consumes_invitation_atomically(
    sqlite_session: Session,
    sqlite_session_factory: sessionmaker[Session],
) -> None:
    account = _persist_account(sqlite_session)
    account.status = AccountStatus.UNINITIALIZED
    invitation = InvitationCode(batch="batch-1", code="invite-1")
    sqlite_session.add_all([account, invitation])
    sqlite_session.commit()
    initialized_at = datetime(2026, 8, 10, 12, 0)
    factory = SQLAlchemyAccountUnitOfWorkFactory(sqlite_session_factory)

    with factory() as unit_of_work:
        consumed = unit_of_work.invitations.consume(
            code="invite-1",
            account_id="account-1",
            workspace_id="workspace-1",
            used_at=initialized_at,
        )
        result = unit_of_work.accounts.initialize(
            "account-1",
            AccountInitialization(
                interface_language="zh-Hans",
                interface_theme="light",
                timezone="Asia/Shanghai",
                initialized_at=initialized_at,
            ),
        )
        unit_of_work.commit()

    assert consumed is True
    assert result is not None
    assert result.status == "active"
    sqlite_session.expire_all()
    persisted_account = sqlite_session.get(Account, "account-1")
    persisted_invitation = sqlite_session.get(InvitationCode, invitation.id)
    assert persisted_account is not None
    assert persisted_account.status == AccountStatus.ACTIVE
    assert persisted_account.interface_language == "zh-Hans"
    assert persisted_account.timezone == "Asia/Shanghai"
    assert persisted_account.initialized_at == initialized_at
    assert persisted_invitation is not None
    assert persisted_invitation.status == InvitationCodeStatus.USED
    assert persisted_invitation.used_by_account_id == "account-1"
    assert persisted_invitation.used_by_tenant_id == "workspace-1"


def test_unit_of_work_updates_email_and_removes_integrations_atomically(
    sqlite_session: Session,
    sqlite_session_factory: sessionmaker[Session],
) -> None:
    _persist_account(sqlite_session)
    integration = AccountIntegrate(
        account_id="account-1",
        provider="google",
        open_id="google-user",
        encrypted_token="encrypted-token",
    )
    sqlite_session.add(integration)
    sqlite_session.commit()
    integration_id = integration.id
    factory = SQLAlchemyAccountUnitOfWorkFactory(sqlite_session_factory)

    with factory() as unit_of_work:
        assert unit_of_work.accounts.email_exists("new@example.com") is False
        result = unit_of_work.accounts.update_email("account-1", "new@example.com")
        unit_of_work.integrations.delete_for_account("account-1")
        unit_of_work.commit()

    assert result is not None
    assert result.email == "new@example.com"
    sqlite_session.expire_all()
    persisted = sqlite_session.get(Account, "account-1")
    assert persisted is not None
    assert persisted.email == "new@example.com"
    assert sqlite_session.get(AccountIntegrate, integration_id) is None
