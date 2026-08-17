from __future__ import annotations

import importlib.util
from collections.abc import Callable, Generator
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from pathlib import Path
from threading import Event
from typing import Protocol, cast

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.exc import IntegrityError

import models

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "migrations/versions/2026_08_17_1200-c4e8a1d7f2b9_deduplicate_app_scoped_end_users.py"
)
_CANONICAL_ID = "00000000-0000-0000-0000-000000000001"
_DUPLICATE_ID = "00000000-0000-0000-0000-000000000002"
_RACING_ID = "00000000-0000-0000-0000-000000000003"
_TENANT_ID = "00000000-0000-0000-0000-000000000101"
_APP_ID = "00000000-0000-0000-0000-000000000201"


class _MigrationModule(Protocol):
    op: Operations
    upgrade: Callable[[], None]
    _create_unique_index: Callable[[str], None]
    _DIRECT_REFERENCES: tuple[tuple[str, str], ...]
    _ROLE_REFERENCES: tuple[tuple[str, str], ...]


def _load_migration() -> _MigrationModule:
    spec = importlib.util.spec_from_file_location(_MIGRATION_PATH.stem, _MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load migration {_MIGRATION_PATH.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast(_MigrationModule, module)


@pytest.fixture(params=("postgresql", "mysql"), scope="module")
def migration_engine(request: pytest.FixtureRequest) -> Generator[tuple[str, sa.Engine], None, None]:
    backend = cast(str, request.param)
    if backend == "postgresql":
        testcontainers_postgres = pytest.importorskip("testcontainers.postgres")
        container = testcontainers_postgres.PostgresContainer("postgres:15-alpine")
    else:
        testcontainers_mysql = pytest.importorskip("testcontainers.mysql")
        container = testcontainers_mysql.MySqlContainer("mysql:8.0")

    container.start()
    raw_url = container.get_connection_url()
    engine = sa.create_engine(raw_url.replace("mysql://", "mysql+pymysql://", 1))
    try:
        yield backend, engine
    finally:
        engine.dispose()
        container.stop()


def _create_legacy_schema(module: _MigrationModule, engine: sa.Engine) -> sa.MetaData:
    metadata = sa.MetaData()
    sa.Table(
        "end_users",
        metadata,
        sa.Column("id", models.types.StringUUID(), primary_key=True),
        sa.Column("tenant_id", models.types.StringUUID(), nullable=False),
        sa.Column("app_id", models.types.StringUUID()),
        sa.Column("session_id", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for table_name, column_name in module._DIRECT_REFERENCES:
        sa.Table(table_name, metadata, sa.Column(column_name, models.types.StringUUID()))
    for table_name, column_name in module._ROLE_REFERENCES:
        columns = [
            sa.Column(column_name, models.types.StringUUID()),
            sa.Column("created_by_role", sa.String(32)),
        ]
        if table_name == "upload_files":
            columns.append(sa.Column("used_by", models.types.StringUUID()))
        sa.Table(table_name, metadata, *columns)
    metadata.create_all(engine)
    return metadata


def _seed_duplicates(module: _MigrationModule, engine: sa.Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO end_users (id, tenant_id, app_id, session_id, created_at)
                VALUES
                    (:canonical_id, :tenant_id, :app_id, 'user-1', '2026-01-01 00:00:00'),
                    (:duplicate_id, :tenant_id, :app_id, 'user-1', '2026-01-02 00:00:00')
                """
            ),
            {
                "canonical_id": _CANONICAL_ID,
                "duplicate_id": _DUPLICATE_ID,
                "tenant_id": _TENANT_ID,
                "app_id": _APP_ID,
            },
        )
        for table_name, column_name in module._DIRECT_REFERENCES:
            connection.execute(
                sa.text(f"INSERT INTO {table_name} ({column_name}) VALUES (:duplicate_id)"),
                {"duplicate_id": _DUPLICATE_ID},
            )
        for table_name, column_name in module._ROLE_REFERENCES:
            used_by_column = ", used_by" if table_name == "upload_files" else ""
            used_by_value = ", :duplicate_id" if table_name == "upload_files" else ""
            connection.execute(
                sa.text(
                    f"INSERT INTO {table_name} ({column_name}, created_by_role{used_by_column}) "
                    f"VALUES (:duplicate_id, 'end_user'{used_by_value})"
                ),
                {"duplicate_id": _DUPLICATE_ID},
            )


def _insert_racing_duplicate(engine: sa.Engine, started: Event) -> None:
    started.set()
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO end_users (id, tenant_id, app_id, session_id, created_at)
                VALUES (:id, :tenant_id, :app_id, 'user-1', '2026-01-03 00:00:00')
                """
            ),
            {"id": _RACING_ID, "tenant_id": _TENANT_ID, "app_id": _APP_ID},
        )


def _run_upgrade_with_racing_insert(module: _MigrationModule, engine: sa.Engine) -> None:
    writer_started = Event()
    writer: Future[None] | None = None

    with ThreadPoolExecutor(max_workers=1) as executor:
        with engine.begin() as connection:
            operations = Operations(MigrationContext.configure(connection))
            original_create_unique_index = module._create_unique_index

            def create_unique_index(dialect_name: str) -> None:
                nonlocal writer
                writer = executor.submit(_insert_racing_duplicate, engine, writer_started)
                assert writer_started.wait(timeout=5)
                with pytest.raises(TimeoutError):
                    writer.result(timeout=0.2)
                original_create_unique_index(dialect_name)

            original_op = module.op
            module.op = operations
            module._create_unique_index = create_unique_index
            try:
                module.upgrade()
            finally:
                module.op = original_op
                module._create_unique_index = original_create_unique_index

        assert writer is not None
        writer.result(timeout=5)


def test_migration_blocks_duplicate_insert_until_unique_index_exists(
    migration_engine: tuple[str, sa.Engine],
) -> None:
    _backend, engine = migration_engine
    module = _load_migration()
    metadata = _create_legacy_schema(module, engine)
    try:
        _seed_duplicates(module, engine)
        _run_upgrade_with_racing_insert(module, engine)

        with engine.connect() as connection:
            end_user_ids = {str(value) for value in connection.scalars(sa.text("SELECT id FROM end_users")).all()}
            assert end_user_ids == {_CANONICAL_ID}
            reference_id = connection.scalar(sa.text("SELECT from_end_user_id FROM conversations"))
            assert str(reference_id) == _CANONICAL_ID

        indexes = {index["name"] for index in sa.inspect(engine).get_indexes("end_users")}
        assert "end_user_tenant_app_session_id_unique" in indexes
    finally:
        metadata.drop_all(engine)
