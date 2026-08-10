"""Framework-neutral errors shared by account application services."""


class AccountNotFoundError(Exception):
    """The admitted account no longer exists."""


class CurrentAccountPasswordIncorrectError(Exception):
    """The supplied current password does not match the account credential."""


class AvatarFileNotFoundError(Exception):
    """The requested avatar file does not exist or is not owned by the account."""


class AccountAlreadyInitializedError(Exception):
    """The account is already active and cannot be initialized again."""


class MissingInvitationCodeError(ValueError):
    """Cloud account initialization requires an invitation code."""


class InvalidInvitationCodeError(Exception):
    """The invitation code is missing, used, or otherwise invalid."""


class InvalidAccountDeletionVerificationError(Exception):
    """The account deletion token or verification code is invalid."""


class AccountDeletionRateLimitError(Exception):
    """Too many account deletion verification emails were requested."""

    def __init__(self, retry_after_minutes: int) -> None:
        super().__init__(retry_after_minutes)
        self.retry_after_minutes = retry_after_minutes


class ChangeEmailSendIPLimitedError(Exception):
    """The caller IP exceeded the email-send policy."""


class ChangeEmailSendRateLimitError(Exception):
    """Too many change-email messages were requested for the address."""

    def __init__(self, retry_after_minutes: int) -> None:
        super().__init__(retry_after_minutes)
        self.retry_after_minutes = retry_after_minutes


class InvalidChangeEmailTokenError(Exception):
    """The token is absent, malformed, in the wrong phase, or bound elsewhere."""


class InvalidChangeEmailAddressError(Exception):
    """The request address does not match the account or token state."""


class ChangeEmailVerificationLimitError(Exception):
    """Too many invalid verification-code attempts were made."""


class InvalidChangeEmailCodeError(Exception):
    """The verification code does not match the current token."""


class AccountEmailFrozenError(Exception):
    """The target email is temporarily frozen by account policy."""


class AccountEmailAlreadyInUseError(Exception):
    """The target email already belongs to an account."""


class EducationDiscountPausedError(Exception):
    """Education discount activation is temporarily paused."""
