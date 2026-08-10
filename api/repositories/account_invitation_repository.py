"""SQLAlchemy implementation of the account invitation persistence port."""

from datetime import datetime
from typing import override

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.account import InvitationCode, InvitationCodeStatus
from services.account_ports import AccountInvitationRepository


class SQLAlchemyAccountInvitationRepository(AccountInvitationRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    @override
    def consume(
        self,
        *,
        code: str,
        account_id: str,
        workspace_id: str,
        used_at: datetime,
    ) -> bool:
        invitation = self._session.scalar(
            select(InvitationCode)
            .where(
                InvitationCode.code == code,
                InvitationCode.status == InvitationCodeStatus.UNUSED,
            )
            .limit(1)
        )
        if invitation is None:
            return False

        invitation.status = InvitationCodeStatus.USED
        invitation.used_at = used_at
        invitation.used_by_tenant_id = workspace_id
        invitation.used_by_account_id = account_id
        self._session.flush()
        return True
