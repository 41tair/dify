from __future__ import annotations

import importlib.util
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, cast

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.exc import IntegrityError

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "migrations/versions/2026_08_17_1200-c4e8a1d7f2b9_deduplicate_app_scoped_end_users.py"
)
_CANONICAL_ID = "00000000-0000-0000-0000-000000000001"
_DUPLICATE_ID = "00000000-0000-0000-0000-000000000002"


class _MigrationModule(Protocol):
    op: Operations
    upgrade: Callable[[], None]
    downgrade: Callable[[], None]
    _DIRECT_REFERENCES: tuple[tuple[str, str], ...]
    _ROLE_REFERENCES: tuple[tuple[str, str], ...]


def _load_migration() -> _MigrationModule:
    spec = importlib.util.spec_from_file_location(_MIGRATION_PATH.stem, _MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load migration {_MIGRATION_PATH.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast(_MigrationModule, module)


def _run_step(module: _MigrationModule, engine: sa.Engine, step: str) -> None:
    with engine.begin() as connection:
        original_op = module.op
        module.op = Operations(MigrationContext.configure(connection))
        try:
            getattr(module, step)()
        finally:
            module.op = original_op


def _create_legacy_schema(module: _MigrationModule, engine: sa.Engine) -> None:
    metadata = sa.MetaData()
    sa.Table(
        "end_users",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("app_id", sa.String(36)),
        sa.Column("session_id", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for table_name, column_name in module._DIRECT_REFERENCES:
        sa.Table(table_name, metadata, sa.Column(column_name, sa.String(36)))
    for table_name, column_name in module._ROLE_REFERENCES:
        if table_name == "upload_files":
            sa.Table(
                table_name,
                metadata,
                sa.Column(column_name, sa.String(36)),
                sa.Column("created_by_role", sa.String(32)),
                sa.Column("used_by", sa.String(36)),
            )
        else:
            sa.Table(
                table_name,
                metadata,
                sa.Column(column_name, sa.String(36)),
                sa.Column("created_by_role", sa.String(32)),
            )
    metadata.create_all(engine)


def _insert_legacy_rows(module: _MigrationModule, engine: sa.Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO end_users (id, tenant_id, app_id, session_id, created_at)
                VALUES
                    (:canonical_id, 'tenant-1', 'app-1', 'user-1', '2026-01-01 00:00:00'),
                    (:duplicate_id, 'tenant-1', 'app-1', 'user-1', '2026-01-02 00:00:00'),
                    ('00000000-0000-0000-0000-000000000003', 'tenant-1', NULL, 'shared', '2026-01-01'),
                    ('00000000-0000-0000-0000-000000000004', 'tenant-1', NULL, 'shared', '2026-01-02')
                """
            ),
            {"canonical_id": _CANONICAL_ID, "duplicate_id": _DUPLICATE_ID},
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
                    f"VALUES (:duplicate_id, 'end_user'{used_by_value}), (:duplicate_id, 'account'{used_by_value})"
                ),
                {"duplicate_id": _DUPLICATE_ID},
            )


def test_upgrade_redirects_all_references_and_enforces_unique_identity() -> None:
    module = _load_migration()
    engine = sa.create_engine("sqlite:///:memory:")
    _create_legacy_schema(module, engine)
    _insert_legacy_rows(module, engine)

    _run_step(module, engine, "upgrade")

    with engine.connect() as connection:
        end_user_ids = connection.scalars(sa.text("SELECT id FROM end_users ORDER BY id")).all()
        assert _DUPLICATE_ID not in end_user_ids
        assert len(end_user_ids) == 3

        for table_name, column_name in module._DIRECT_REFERENCES:
            assert connection.scalar(sa.text(f"SELECT {column_name} FROM {table_name}")) == _CANONICAL_ID
        for table_name, column_name in module._ROLE_REFERENCES:
            values_by_role = dict(
                connection.execute(
                    sa.text(f"SELECT created_by_role, {column_name} FROM {table_name} ORDER BY created_by_role")
                )
                .tuples()
                .all()
            )
            assert values_by_role == {"account": _DUPLICATE_ID, "end_user": _CANONICAL_ID}
        assert connection.scalar(sa.text("SELECT used_by FROM upload_files LIMIT 1")) == _CANONICAL_ID

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO end_users (id, tenant_id, app_id, session_id, created_at)
                VALUES ('00000000-0000-0000-0000-000000000005', 'tenant-1', 'app-1', 'user-1', '2026-01-03')
                """
            )
        )


def test_downgrade_removes_unique_index_without_recreating_duplicates() -> None:
    module = _load_migration()
    engine = sa.create_engine("sqlite:///:memory:")
    _create_legacy_schema(module, engine)
    _insert_legacy_rows(module, engine)
    _run_step(module, engine, "upgrade")

    _run_step(module, engine, "downgrade")

    index_names = {index["name"] for index in sa.inspect(engine).get_indexes("end_users")}
    assert "end_user_tenant_app_session_id_unique" not in index_names
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO end_users (id, tenant_id, app_id, session_id, created_at)
                VALUES ('00000000-0000-0000-0000-000000000006', 'tenant-1', 'app-1', 'user-1', '2026-01-04')
                """
            )
        )
    with engine.connect() as connection:
        assert connection.scalar(sa.text("SELECT COUNT(*) FROM end_users WHERE app_id = 'app-1'")) == 2
