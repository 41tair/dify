"""Database repository for the end-user detail read model."""

from typing import override

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from models.model import EndUser
from services.end_user_query_service import EndUserQuery
from services.entities.end_user_entities import EndUserRecord


class EndUserQueryRepository(EndUserQuery):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    @override
    def find_by_id(self, *, tenant_id: str, app_id: str, end_user_id: str) -> EndUserRecord | None:
        stmt = (
            select(
                EndUser.id,
                EndUser.tenant_id,
                EndUser.app_id,
                EndUser.type,
                EndUser.external_user_id,
                EndUser.name,
                EndUser._is_anonymous,
                EndUser.session_id,
                EndUser.created_at,
                EndUser.updated_at,
            )
            .where(
                EndUser.id == end_user_id,
                EndUser.tenant_id == tenant_id,
                EndUser.app_id == app_id,
            )
        )

        with self._session_factory() as session:
            row = session.execute(stmt).one_or_none()

        if row is None:
            return None

        (
            record_id,
            record_tenant_id,
            record_app_id,
            record_type,
            external_user_id,
            name,
            is_anonymous,
            session_id,
            created_at,
            updated_at,
        ) = row
        return EndUserRecord(
            id=record_id,
            tenant_id=record_tenant_id,
            app_id=record_app_id,
            type=record_type.value,
            external_user_id=external_user_id,
            name=name,
            is_anonymous=is_anonymous,
            session_id=session_id,
            created_at=created_at,
            updated_at=updated_at,
        )
