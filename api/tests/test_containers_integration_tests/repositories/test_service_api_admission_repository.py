from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from sqlalchemy import Engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

from models import TenantAccountRole
from models.account import Account, Tenant, TenantAccountJoin
from models.enums import EndUserType
from models.model import App, EndUser
from repositories.service_api_admission_repository import SqlAlchemyServiceApiAdmissionRepository


def _create_admitted_app(session: Session) -> App:
    tenant = Tenant(name=f"Admission tenant {uuid4()}")
    account = Account(
        name=f"Admission owner {uuid4()}",
        email=f"admission-{uuid4()}@example.com",
        password="hashed-password",
        password_salt="salt",
        interface_language="en-US",
        timezone="UTC",
    )
    session.add_all([tenant, account])
    session.flush()
    session.add(
        TenantAccountJoin(
            tenant_id=tenant.id,
            account_id=account.id,
            role=TenantAccountRole.OWNER,
            current=True,
        )
    )
    app = App(
        tenant_id=tenant.id,
        name=f"Admission app {uuid4()}",
        description="",
        mode="chat",
        icon_type="emoji",
        icon="bot",
        icon_background="#FFFFFF",
        enable_site=False,
        enable_api=True,
        api_rpm=100,
        api_rph=100,
        is_demo=False,
        is_public=False,
        is_universal=False,
        created_by=account.id,
        updated_by=account.id,
    )
    session.add(app)
    session.commit()
    return app


def _session_factory(session: Session) -> sessionmaker[Session]:
    engine = session.get_bind()
    assert isinstance(engine, Engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_postgres_admission_keeps_projection_and_creation_in_one_short_scope(
    db_session_with_containers: Session,
) -> None:
    app = _create_admitted_app(db_session_with_containers)
    app_id = app.id
    tenant_id = app.tenant_id
    factory = _session_factory(db_session_with_containers)
    repository = SqlAlchemyServiceApiAdmissionRepository(session_factory=factory)
    statements: list[str] = []

    def record_statement(_conn, _cursor, statement: str, _parameters, _context, _executemany) -> None:
        operation = statement.lstrip().partition(" ")[0].upper()
        if operation in {"SELECT", "INSERT"}:
            statements.append(operation)

    event.listen(factory.kw["bind"], "before_cursor_execute", record_statement)
    try:
        with repository.open(
            app_id=app_id,
            end_user_external_id="database-user",
            require_tenant_owner=True,
        ) as admission:
            assert admission.snapshot is not None
            assert admission.snapshot.app_id == app_id
            assert admission.snapshot.tenant_id == tenant_id
            assert admission.snapshot.tenant_owner_exists is True
            assert admission.snapshot.end_user is None
            identity = admission.create_end_user(external_user_id="database-user")
    finally:
        event.remove(factory.kw["bind"], "before_cursor_execute", record_statement)

    assert statements == ["SELECT", "INSERT"]
    with factory() as verification_session:
        stored = verification_session.scalar(
            select(EndUser).where(
                EndUser.id == identity.id,
                EndUser.tenant_id == tenant_id,
                EndUser.app_id == app_id,
                EndUser.session_id == "database-user",
            )
        )
        assert stored is not None
        assert stored.type == EndUserType.SERVICE_API


def test_postgres_full_admission_resolves_twenty_concurrent_creators_after_initial_read(
    db_session_with_containers: Session,
) -> None:
    app = _create_admitted_app(db_session_with_containers)
    app_id = app.id
    tenant_id = app.tenant_id
    factory = _session_factory(db_session_with_containers)
    barrier = Barrier(20)

    def resolve() -> str:
        repository = SqlAlchemyServiceApiAdmissionRepository(session_factory=factory)
        with repository.open(
            app_id=app_id,
            end_user_external_id="concurrent-database-user",
            require_tenant_owner=False,
        ) as admission:
            assert admission.snapshot is not None
            assert admission.snapshot.end_user is None
            barrier.wait()
            return admission.create_end_user(external_user_id="concurrent-database-user").id

    with ThreadPoolExecutor(max_workers=20) as executor:
        resolved_ids = list(executor.map(lambda _index: resolve(), range(20)))

    assert len(set(resolved_ids)) == 1
    with factory() as verification_session:
        stored_count = verification_session.scalar(
            select(func.count())
            .select_from(EndUser)
            .where(
                EndUser.tenant_id == tenant_id,
                EndUser.app_id == app_id,
                EndUser.session_id == "concurrent-database-user",
            )
        )
    assert stored_count == 1
