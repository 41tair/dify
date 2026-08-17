from datetime import datetime

from sqlalchemy.orm import Session, sessionmaker

from models.enums import EndUserType
from models.model import EndUser
from repositories.end_user_query_repository import EndUserQueryRepository
from services.entities.end_user_entities import EndUserRecord


def _end_user(*, end_user_id: str, tenant_id: str, app_id: str) -> EndUser:
    return EndUser(
        id=end_user_id,
        tenant_id=tenant_id,
        app_id=app_id,
        type=EndUserType.SERVICE_API,
        external_user_id=f"external-{end_user_id}",
        name=f"User {end_user_id}",
        is_anonymous=True,
        session_id=f"session-{end_user_id}",
        created_at=datetime(2024, 1, 1),
        updated_at=datetime(2024, 1, 2),
    )


def test_find_by_id_returns_detached_read_model_scoped_to_tenant_and_app(
    sqlite_session: Session,
    sqlite_session_factory: sessionmaker[Session],
) -> None:
    visible = _end_user(end_user_id="visible", tenant_id="tenant-1", app_id="app-1")
    other_app = _end_user(end_user_id="other-app", tenant_id="tenant-1", app_id="app-2")
    other_tenant = _end_user(end_user_id="other-tenant", tenant_id="tenant-2", app_id="app-1")
    sqlite_session.add_all([visible, other_app, other_tenant])
    sqlite_session.commit()

    repository = EndUserQueryRepository(session_factory=sqlite_session_factory)

    assert repository.find_by_id(tenant_id="tenant-1", app_id="app-1", end_user_id=visible.id) == EndUserRecord(
        id=visible.id,
        tenant_id=visible.tenant_id,
        app_id=visible.app_id,
        type=EndUserType.SERVICE_API.value,
        external_user_id=visible.external_user_id,
        name=visible.name,
        is_anonymous=True,
        session_id=visible.session_id,
        created_at=visible.created_at,
        updated_at=visible.updated_at,
    )
    assert repository.find_by_id(tenant_id="tenant-1", app_id="app-2", end_user_id=visible.id) is None
    assert repository.find_by_id(tenant_id="tenant-2", app_id="app-1", end_user_id=visible.id) is None
    assert repository.find_by_id(tenant_id="tenant-1", app_id="app-1", end_user_id="missing") is None
