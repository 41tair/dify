"""Short-session persistence adapter for Service API admission."""

from collections.abc import Generator
from contextlib import contextmanager
from typing import override

from sqlalchemy import and_, exists, literal, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from machinery.context import ServiceApiEndUserIdentity
from models import Account, Tenant, TenantAccountJoin
from models.account import TenantAccountRole
from models.enums import EndUserType
from models.model import App, EndUser
from repositories.end_user_repository import create_end_user_or_get_concurrent
from services.entities.service_api_entities import ServiceApiAdmissionSnapshot
from services.service_api_admission_service import (
    ServiceApiAdmissionRepository,
    ServiceApiAdmissionScope,
)


class _SqlAlchemyServiceApiAdmissionScope(ServiceApiAdmissionScope):
    def __init__(
        self,
        *,
        session: Session,
        snapshot: ServiceApiAdmissionSnapshot | None,
    ) -> None:
        self._session = session
        self._snapshot = snapshot

    @property
    @override
    def snapshot(self) -> ServiceApiAdmissionSnapshot | None:
        return self._snapshot

    @override
    def create_end_user(self, *, external_user_id: str) -> ServiceApiEndUserIdentity:
        if self._snapshot is None:
            raise RuntimeError("Cannot create an EndUser without an admitted app")

        end_user = create_end_user_or_get_concurrent(
            self._session,
            end_user_type=EndUserType.SERVICE_API,
            tenant_id=self._snapshot.tenant_id,
            app_id=self._snapshot.app_id,
            session_id=external_user_id,
        )

        return ServiceApiEndUserIdentity(
            id=end_user.id,
            external_user_id=end_user.external_user_id or external_user_id,
        )


class SqlAlchemyServiceApiAdmissionRepository(ServiceApiAdmissionRepository):
    def __init__(self, *, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    @contextmanager
    @override
    def open(
        self,
        *,
        app_id: str,
        end_user_external_id: str | None,
        require_tenant_owner: bool,
    ) -> Generator[ServiceApiAdmissionScope, None, None]:
        tenant_owner_exists: ColumnElement[bool]
        if require_tenant_owner:
            tenant_owner_exists = exists(
                select(Account.id)
                .select_from(TenantAccountJoin)
                .join(Account, Account.id == TenantAccountJoin.account_id)
                .where(
                    TenantAccountJoin.tenant_id == App.tenant_id,
                    TenantAccountJoin.role == TenantAccountRole.OWNER,
                )
            )
        else:
            tenant_owner_exists = literal(True)
        stmt = (
            select(
                App.id.label("app_id"),
                App.tenant_id,
                App.mode.label("app_mode"),
                App.status.label("app_status"),
                App.enable_api,
                Tenant.status.label("tenant_status"),
                tenant_owner_exists.label("tenant_owner_exists"),
            )
            .outerjoin(Tenant, Tenant.id == App.tenant_id)
            .where(App.id == app_id)
        )

        if end_user_external_id is not None:
            stmt = stmt.add_columns(
                EndUser.id.label("end_user_id"),
                EndUser.external_user_id,
            ).outerjoin(
                EndUser,
                and_(
                    EndUser.tenant_id == App.tenant_id,
                    EndUser.app_id == App.id,
                    EndUser.session_id == end_user_external_id,
                ),
            )

        with self._session_factory.begin() as session:
            row = session.execute(stmt).one_or_none()
            snapshot = None
            if row is not None:
                mapping = row._mapping
                resolved_end_user = None
                if end_user_external_id is not None and mapping["end_user_id"] is not None:
                    resolved_end_user = ServiceApiEndUserIdentity(
                        id=mapping["end_user_id"],
                        external_user_id=mapping["external_user_id"] or end_user_external_id,
                    )

                tenant_status = mapping["tenant_status"]
                snapshot = ServiceApiAdmissionSnapshot(
                    app_id=mapping["app_id"],
                    tenant_id=mapping["tenant_id"],
                    app_mode=str(mapping["app_mode"]),
                    app_status=str(mapping["app_status"]),
                    api_enabled=mapping["enable_api"],
                    tenant_status=str(tenant_status) if tenant_status is not None else None,
                    tenant_owner_exists=mapping["tenant_owner_exists"],
                    end_user=resolved_end_user,
                )

            yield _SqlAlchemyServiceApiAdmissionScope(session=session, snapshot=snapshot)
