"""Framework-neutral errors shared by account application services."""


class AccountNotFoundError(Exception):
    """The admitted account no longer exists."""


class CurrentAccountPasswordIncorrectError(Exception):
    """The supplied current password does not match the account credential."""


class AvatarFileNotFoundError(Exception):
    """The requested avatar file does not exist or is not owned by the account."""
