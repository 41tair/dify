"""Persistence helpers for concurrency-safe EndUser identity resolution."""

from collections.abc import Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from models.enums import EndUserType
from models.model import DefaultEndUserSessionID, EndUser


def normalize_end_user_session_id(user_id: str | None) -> str:
    return user_id or DefaultEndUserSessionID.DEFAULT_SESSION_ID


def _end_user_identity_query(*, tenant_id: str, app_id: str, session_id: str):
    return select(EndUser).where(
        EndUser.tenant_id == tenant_id,
        EndUser.app_id == app_id,
        EndUser.session_id == session_id,
    )


def find_end_user(
    session: Session,
    *,
    tenant_id: str,
    app_id: str,
    session_id: str,
) -> EndUser | None:
    return session.execute(
        _end_user_identity_query(tenant_id=tenant_id, app_id=app_id, session_id=session_id)
    ).scalar_one_or_none()


def _find_end_user_with_current_read(
    session: Session,
    *,
    tenant_id: str,
    app_id: str,
    session_id: str,
) -> EndUser | None:
    """Read the winning concurrent row outside an earlier consistent-read snapshot.

    InnoDB's default REPEATABLE READ keeps the snapshot established by the
    initial identity lookup. A locking read is a current read, so after a
    duplicate-key wait it can observe the row committed by the winning writer.
    """

    return session.execute(
        _end_user_identity_query(tenant_id=tenant_id, app_id=app_id, session_id=session_id).with_for_update(read=True)
    ).scalar_one_or_none()


def create_end_user_or_get_concurrent(
    session: Session,
    *,
    end_user_type: EndUserType,
    tenant_id: str,
    app_id: str,
    session_id: str,
    is_anonymous: bool | None = None,
    external_user_id: str | None = None,
    name: str | None = None,
) -> EndUser:
    end_user = EndUser(
        tenant_id=tenant_id,
        app_id=app_id,
        type=end_user_type,
        is_anonymous=(
            session_id == DefaultEndUserSessionID.DEFAULT_SESSION_ID if is_anonymous is None else is_anonymous
        ),
        session_id=session_id,
        external_user_id=session_id if external_user_id is None else external_user_id,
        name=name,
    )
    try:
        with session.begin_nested():
            session.add(end_user)
            session.flush()
        return end_user
    except IntegrityError:
        concurrent = _find_end_user_with_current_read(
            session,
            tenant_id=tenant_id,
            app_id=app_id,
            session_id=session_id,
        )
        if concurrent is None:
            raise
        return concurrent


def resolve_end_user(
    session: Session,
    *,
    end_user_type: EndUserType,
    tenant_id: str,
    app_id: str,
    user_id: str | None,
    is_anonymous: bool | None = None,
    external_user_id: str | None = None,
    name: str | None = None,
) -> EndUser:
    session_id = normalize_end_user_session_id(user_id)
    end_user = find_end_user(
        session,
        tenant_id=tenant_id,
        app_id=app_id,
        session_id=session_id,
    )
    if end_user is None:
        end_user = create_end_user_or_get_concurrent(
            session,
            end_user_type=end_user_type,
            tenant_id=tenant_id,
            app_id=app_id,
            session_id=session_id,
            is_anonymous=is_anonymous,
            external_user_id=external_user_id,
            name=name,
        )

    return end_user


class EndUserRepository:
    """Repository owning short sessions for legacy EndUser entry points."""

    def __init__(self, *, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get_by_id(self, *, tenant_id: str, app_id: str, end_user_id: str) -> EndUser | None:
        with self._session_factory() as session:
            return session.scalar(
                select(EndUser).where(
                    EndUser.id == end_user_id,
                    EndUser.tenant_id == tenant_id,
                    EndUser.app_id == app_id,
                )
            )

    def get_or_create(
        self,
        *,
        end_user_type: EndUserType,
        tenant_id: str,
        app_id: str,
        user_id: str | None,
    ) -> EndUser:
        with self._session_factory.begin() as session:
            return resolve_end_user(
                session,
                end_user_type=end_user_type,
                tenant_id=tenant_id,
                app_id=app_id,
                user_id=user_id,
            )

    def get_or_create_batch(
        self,
        *,
        end_user_type: EndUserType,
        tenant_id: str,
        app_ids: Sequence[str],
        user_id: str,
    ) -> Mapping[str, EndUser]:
        unique_app_ids = list(dict.fromkeys(app_ids))
        if not unique_app_ids:
            return {}

        session_id = normalize_end_user_session_id(user_id)
        with self._session_factory.begin() as session:
            existing = session.scalars(
                select(EndUser).where(
                    EndUser.tenant_id == tenant_id,
                    EndUser.app_id.in_(unique_app_ids),
                    EndUser.session_id == session_id,
                )
            ).all()
            result = {end_user.app_id: end_user for end_user in existing if end_user.app_id is not None}

            for app_id in unique_app_ids:
                end_user = result.get(app_id)
                if end_user is None:
                    end_user = create_end_user_or_get_concurrent(
                        session,
                        end_user_type=end_user_type,
                        tenant_id=tenant_id,
                        app_id=app_id,
                        session_id=session_id,
                    )
                    result[app_id] = end_user
            return result
