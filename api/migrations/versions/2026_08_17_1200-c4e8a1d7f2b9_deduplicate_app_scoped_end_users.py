"""deduplicate app-scoped end users

Revision ID: c4e8a1d7f2b9
Revises: 56124e050600
Create Date: 2026-08-17 12:00:00.000000

The application identity for an app-scoped EndUser is
``(tenant_id, app_id, session_id)``.  Older code only indexed type-scoped
variants, so concurrent first requests could create multiple identities.

This migration keeps the oldest row in each duplicate group, redirects known
logical references, removes the duplicate rows, and finally creates the unique
index used by conflict-safe find-or-create. PostgreSQL writers are blocked for
the transactional migration window. MySQL explicitly locks every touched table
during cleanup and hands off to an ALTER TABLE lock while building the index.
Downgrade removes the index but cannot recreate deleted duplicate identities.
"""

import sqlalchemy as sa
from alembic import op

import models

# revision identifiers, used by Alembic.
revision = "c4e8a1d7f2b9"
down_revision = "56124e050600"
branch_labels = None
depends_on = None

_MAPPING_TABLE = "_end_user_deduplication_map"
_UNIQUE_INDEX = "end_user_tenant_app_session_id_unique"
_DIRECT_REFERENCES = (
    ("conversations", "from_end_user_id"),
    ("messages", "from_end_user_id"),
    ("message_feedbacks", "from_end_user_id"),
    ("human_input_forms", "submission_end_user_id"),
)
_ROLE_REFERENCES = (
    ("message_files", "created_by"),
    ("message_agent_thoughts", "created_by"),
    ("upload_files", "created_by"),
    ("workflow_runs", "created_by"),
    ("workflow_node_executions", "created_by"),
    ("workflow_app_logs", "created_by"),
    ("workflow_archive_logs", "created_by"),
    ("workflow_trigger_logs", "created_by"),
    ("saved_messages", "created_by"),
    ("pinned_conversations", "created_by"),
    ("dataset_queries", "created_by"),
)


def _redirect_reference(
    table: str,
    column: str,
    *,
    dialect_name: str,
    role_column: str | None = None,
) -> None:
    role_predicate = ""
    if role_column is not None:
        role_predicate = f" AND {role_column} IN ('end_user', 'end-user')"

    if dialect_name == "mysql":
        op.execute(
            sa.text(
                f"""
                UPDATE {table}
                JOIN {_MAPPING_TABLE}
                    ON {_MAPPING_TABLE}.duplicate_id = {table}.{column}
                SET {table}.{column} = {_MAPPING_TABLE}.canonical_id
                WHERE TRUE {role_predicate}
                """
            )
        )
        return

    op.execute(
        sa.text(
            f"""
            UPDATE {table}
            SET {column} = (
                SELECT canonical_id
                FROM {_MAPPING_TABLE}
                WHERE duplicate_id = {table}.{column}
            )
            WHERE {column} IN (SELECT duplicate_id FROM {_MAPPING_TABLE})
            {role_predicate}
            """
        )
    )


def _unique_index_exists(connection: sa.Connection) -> bool:
    return any(index["name"] == _UNIQUE_INDEX for index in sa.inspect(connection).get_indexes("end_users"))


def _prepare_write_safety(dialect_name: str) -> None:
    touched_tables = {
        _MAPPING_TABLE,
        "end_users",
        *[table for table, _column in _DIRECT_REFERENCES],
        *[table for table, _column in _ROLE_REFERENCES],
    }

    if dialect_name == "postgresql":
        # PostgreSQL holds this lock through the surrounding Alembic
        # transaction, including reference rewrites and index creation.
        lock_targets = ", ".join(sorted(touched_tables))
        op.execute(sa.text(f"LOCK TABLE {lock_targets} IN SHARE MODE"))
        return

    if dialect_name != "mysql":
        return

    lock_targets = ", ".join(f"{table} WRITE" for table in sorted(touched_tables))
    op.execute(sa.text(f"LOCK TABLES {lock_targets}"))


def _create_unique_index(dialect_name: str) -> None:
    if dialect_name == "mysql":
        # LOCK TABLES protects the cleanup/index gap. ALTER TABLE releases that
        # explicit lock, while LOCK=SHARED continues to block DML for the index
        # build itself and still permits reads.
        op.execute(
            sa.text(
                f"""
                ALTER TABLE end_users
                ADD UNIQUE INDEX {_UNIQUE_INDEX} (tenant_id, app_id, session_id),
                ALGORITHM=INPLACE,
                LOCK=SHARED
                """
            )
        )
        return

    op.create_index(
        _UNIQUE_INDEX,
        "end_users",
        ["tenant_id", "app_id", "session_id"],
        unique=True,
    )


def upgrade() -> None:
    connection = op.get_bind()
    dialect_name = connection.dialect.name

    if dialect_name == "mysql":
        # MySQL DDL is not transactional. Make a failed attempt retryable and
        # finish cleanup if the unique index was already created.
        op.execute(sa.text(f"DROP TABLE IF EXISTS {_MAPPING_TABLE}"))
        if _unique_index_exists(connection):
            return

    op.create_table(
        _MAPPING_TABLE,
        sa.Column("duplicate_id", models.types.StringUUID(), nullable=False),
        sa.Column("canonical_id", models.types.StringUUID(), nullable=False),
        sa.PrimaryKeyConstraint("duplicate_id", name="end_user_deduplication_map_pkey"),
    )

    _prepare_write_safety(dialect_name)

    try:
        op.execute(
            sa.text(
                f"""
                INSERT INTO {_MAPPING_TABLE} (duplicate_id, canonical_id)
                SELECT id, canonical_id
                FROM (
                    SELECT
                        id,
                        FIRST_VALUE(id) OVER (
                            PARTITION BY tenant_id, app_id, session_id
                            ORDER BY created_at ASC, id ASC
                        ) AS canonical_id,
                        ROW_NUMBER() OVER (
                            PARTITION BY tenant_id, app_id, session_id
                            ORDER BY created_at ASC, id ASC
                        ) AS duplicate_rank
                    FROM end_users
                    WHERE app_id IS NOT NULL
                ) ranked_end_users
                WHERE duplicate_rank > 1
                """
            )
        )

        for table, column in _DIRECT_REFERENCES:
            _redirect_reference(table, column, dialect_name=dialect_name)

        for table, column in _ROLE_REFERENCES:
            _redirect_reference(
                table,
                column,
                dialect_name=dialect_name,
                role_column="created_by_role",
            )

        # UploadFile has no independent used_by role. UUIDs are globally unique
        # and writers put an EndUser id here when an EndUser consumes the file.
        _redirect_reference("upload_files", "used_by", dialect_name=dialect_name)

        op.execute(sa.text(f"DELETE FROM end_users WHERE id IN (SELECT duplicate_id FROM {_MAPPING_TABLE})"))
        _create_unique_index(dialect_name)
    finally:
        if dialect_name == "mysql":
            # ALTER TABLE already releases explicit table locks; UNLOCK is also
            # required for failures before the ALTER handoff.
            op.execute(sa.text("UNLOCK TABLES"))

    op.drop_table(_MAPPING_TABLE)


def downgrade() -> None:
    op.drop_index(_UNIQUE_INDEX, table_name="end_users")
