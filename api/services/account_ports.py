"""Persistence ports used by account application services."""

from types import TracebackType
from typing import Protocol, Self

from services.entities.account_entities import (
    AccountCredentials,
    AccountIntegrationSnapshot,
    AccountPasswordDigest,
    AccountProfileChanges,
    AccountSnapshot,
)


class AccountRepository(Protocol):
    def get(self, account_id: str) -> AccountSnapshot | None: ...

    def get_credentials(self, account_id: str) -> AccountCredentials | None: ...

    def update_profile(self, account_id: str, changes: AccountProfileChanges) -> AccountSnapshot | None: ...

    def update_password(self, account_id: str, password: AccountPasswordDigest) -> AccountSnapshot | None: ...


class AccountIntegrationRepository(Protocol):
    def list_for_account(self, account_id: str) -> list[AccountIntegrationSnapshot]: ...


class AccountAvatarFileGateway(Protocol):
    def get_owned_signed_url(self, *, account_id: str, upload_file_id: str) -> str | None: ...


class AccountPasswordHasher(Protocol):
    def verify(self, password: str, *, password_hash: str, password_salt: str) -> bool: ...

    def hash(self, password: str) -> AccountPasswordDigest: ...


class UnitOfWork(Protocol):
    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class AccountRepositoryUnitOfWork(UnitOfWork, Protocol):
    @property
    def accounts(self) -> AccountRepository: ...


class AccountIntegrationUnitOfWork(UnitOfWork, Protocol):
    @property
    def integrations(self) -> AccountIntegrationRepository: ...


class AccountUnitOfWork(AccountRepositoryUnitOfWork, AccountIntegrationUnitOfWork, Protocol):
    """Complete IAM account unit of work implemented by the composition root."""


class UnitOfWorkFactory[T: UnitOfWork](Protocol):
    def __call__(self) -> T: ...


type AccountUnitOfWorkFactory = UnitOfWorkFactory[AccountUnitOfWork]
