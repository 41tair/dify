from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from unittest.mock import MagicMock

from sqlalchemy import event, inspect, select
from sqlalchemy.dialects.mysql import dialect as mysql_dialect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from models import Account, Tenant, TenantAccountJoin
from models.account import TenantAccountRole
from models.enums import EndUserType
from models.model import App, AppMode, EndUser, IconType
from repositories.end_user_repository import (
    _find_end_user_with_current_read,
    create_end_user_or_get_concurrent,
)
from repositories.service_api_admission_repository import SqlAlchemyServiceApiAdmissionRepository


def _persist_app(session: Session) -> tuple[Tenant, App]:
    tenant = Tenant(name="Workspace")
    account = Account(name="Owner", email="owner@example.com")
    app = App(
        tenant_id=tenant.id,
        name="Service API App",
        mode=AppMode.CHAT,
        icon_type=IconType.EMOJI,
        icon="chat",
        icon_background="#FFFFFF",
        enable_site=False,
        enable_api=True,
    )
    session.add_all(
        [
            tenant,
            account,
            app,
            TenantAccountJoin(
                tenant_id=tenant.id,
                account_id=account.id,
                role=TenantAccountRole.OWNER,
            ),
        ]
    )
    session.commit()
    return tenant, app


@contextmanager
def _record_data_statements(engine: Engine) -> Iterator[list[str]]:
    statements: list[str] = []

    def record(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        operation = statement.lstrip().partition(" ")[0].upper()
        if operation in {"SELECT", "INSERT", "UPDATE", "DELETE"}:
            statements.append(operation)

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", record)


def test_app_only_admission_reads_all_state_in_one_select(
    sqlite_engine: Engine,
    sqlite_session: Session,
    sqlite_session_factory: sessionmaker[Session],
) -> None:
    tenant, app = _persist_app(sqlite_session)
    repository = SqlAlchemyServiceApiAdmissionRepository(session_factory=sqlite_session_factory)

    with _record_data_statements(sqlite_engine) as statements:
        with repository.open(
            app_id=app.id,
            end_user_external_id=None,
            require_tenant_owner=True,
        ) as admission:
            snapshot = admission.snapshot

    assert statements == ["SELECT"]
    assert snapshot is not None
    assert snapshot.app_id == app.id
    assert snapshot.tenant_id == tenant.id
    assert snapshot.app_mode == "chat"
    assert snapshot.tenant_owner_exists is True
    assert snapshot.end_user is None


def test_existing_end_user_is_resolved_by_the_same_admission_select(
    sqlite_engine: Engine,
    sqlite_session: Session,
    sqlite_session_factory: sessionmaker[Session],
) -> None:
    tenant, app = _persist_app(sqlite_session)
    end_user = EndUser(
        tenant_id=tenant.id,
        app_id=app.id,
        type=EndUserType.SERVICE_API,
        external_user_id="external-1",
        session_id="external-1",
        is_anonymous=False,
    )
    sqlite_session.add(end_user)
    sqlite_session.commit()
    repository = SqlAlchemyServiceApiAdmissionRepository(session_factory=sqlite_session_factory)

    with _record_data_statements(sqlite_engine) as statements:
        with repository.open(
            app_id=app.id,
            end_user_external_id="external-1",
            require_tenant_owner=False,
        ) as admission:
            snapshot = admission.snapshot

    assert statements == ["SELECT"]
    assert snapshot is not None
    assert snapshot.end_user is not None
    assert snapshot.end_user.id == end_user.id
    assert snapshot.end_user.external_user_id == "external-1"


def test_missing_end_user_costs_one_select_and_one_insert(
    sqlite_engine: Engine,
    sqlite_session: Session,
    sqlite_session_factory: sessionmaker[Session],
) -> None:
    tenant, app = _persist_app(sqlite_session)
    repository = SqlAlchemyServiceApiAdmissionRepository(session_factory=sqlite_session_factory)

    with _record_data_statements(sqlite_engine) as statements:
        with repository.open(
            app_id=app.id,
            end_user_external_id="external-new",
            require_tenant_owner=False,
        ) as admission:
            identity = admission.create_end_user(external_user_id="external-new")

    assert statements == ["SELECT", "INSERT"]
    assert identity.external_user_id == "external-new"
    with sqlite_session_factory() as verification_session:
        persisted = verification_session.scalar(select(EndUser).where(EndUser.id == identity.id))
    assert persisted is not None
    assert persisted.tenant_id == tenant.id
    assert persisted.app_id == app.id


def test_duplicate_insert_reselects_canonical_end_user_and_keeps_transaction_usable(
    sqlite_session: Session,
) -> None:
    tenant, app = _persist_app(sqlite_session)
    canonical = EndUser(
        tenant_id=tenant.id,
        app_id=app.id,
        type=EndUserType.SERVICE_API,
        external_user_id="external-1",
        session_id="external-1",
        is_anonymous=False,
    )
    sqlite_session.add(canonical)
    sqlite_session.commit()

    resolved = create_end_user_or_get_concurrent(
        sqlite_session,
        end_user_type=EndUserType.SERVICE_API,
        tenant_id=tenant.id,
        app_id=app.id,
        session_id="external-1",
    )

    assert resolved.id == canonical.id
    assert sqlite_session.scalar(select(EndUser.id).where(EndUser.id == canonical.id)) == canonical.id


def test_concurrent_conflict_reselect_uses_a_mysql_current_read() -> None:
    session = MagicMock(spec=Session)
    session.execute.return_value.scalar_one_or_none.return_value = None

    _find_end_user_with_current_read(
        session,
        tenant_id="tenant-1",
        app_id="app-1",
        session_id="external-1",
    )

    statement = session.execute.call_args.args[0]
    sql = str(statement.compile(dialect=mysql_dialect()))
    assert sql.rstrip().endswith("LOCK IN SHARE MODE")


def test_end_user_model_declares_app_scoped_session_uniqueness(sqlite_engine: Engine) -> None:
    indexes = {index["name"]: index for index in inspect(sqlite_engine).get_indexes("end_users")}

    unique_index = indexes["end_user_tenant_app_session_id_unique"]
    assert unique_index["unique"] == 1
    assert unique_index["column_names"] == ["tenant_id", "app_id", "session_id"]


def test_concurrent_resolvers_converge_on_one_end_user(
    sqlite_session: Session,
    sqlite_session_factory: sessionmaker[Session],
) -> None:
    tenant, app = _persist_app(sqlite_session)

    def resolve_once(_request_number: int) -> str:
        with sqlite_session_factory.begin() as session:
            return create_end_user_or_get_concurrent(
                session,
                end_user_type=EndUserType.SERVICE_API,
                tenant_id=tenant.id,
                app_id=app.id,
                session_id="shared-external-user",
            ).id

    with ThreadPoolExecutor(max_workers=8) as executor:
        resolved_ids = list(executor.map(resolve_once, range(20)))

    assert len(set(resolved_ids)) == 1
    with sqlite_session_factory() as verification_session:
        rows = verification_session.scalars(
            select(EndUser).where(
                EndUser.tenant_id == tenant.id,
                EndUser.app_id == app.id,
                EndUser.session_id == "shared-external-user",
            )
        ).all()
    assert len(rows) == 1
