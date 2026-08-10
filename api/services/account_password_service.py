"""Application service for changing a current account password."""

from machinery.context import RequestContext
from services.account_errors import AccountNotFoundError, CurrentAccountPasswordIncorrectError
from services.account_ports import AccountPasswordHasher, AccountRepositoryUnitOfWork, UnitOfWorkFactory
from services.entities.account_entities import AccountSnapshot


class AccountPasswordService:
    def __init__(
        self,
        *,
        unit_of_work: UnitOfWorkFactory[AccountRepositoryUnitOfWork],
        passwords: AccountPasswordHasher,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._passwords = passwords

    def change(self, context: RequestContext, *, current_password: str, new_password: str) -> AccountSnapshot:
        with self._unit_of_work() as unit_of_work:
            credentials = unit_of_work.accounts.get_credentials(context.account_id)
            if credentials is None:
                raise AccountNotFoundError

            if credentials.password_hash and (
                credentials.password_salt is None
                or not self._passwords.verify(
                    current_password,
                    password_hash=credentials.password_hash,
                    password_salt=credentials.password_salt,
                )
            ):
                raise CurrentAccountPasswordIncorrectError

            password = self._passwords.hash(new_password)
            account = unit_of_work.accounts.update_password(context.account_id, password)
            if account is None:
                raise AccountNotFoundError
            unit_of_work.commit()
        return account
