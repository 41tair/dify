"""Application service for admitting App-scoped Service API requests."""

from contextlib import AbstractContextManager
from enum import StrEnum, auto
from typing import Protocol

from machinery.context import ServiceApiEndUserIdentity, ServiceApiRequestContext
from services.entities.service_api_entities import (
    ResolvedServiceApiCredential,
    ServiceApiAdmissionRequirement,
    ServiceApiAdmissionSnapshot,
)


class ServiceApiTokenGateway(Protocol):
    def resolve(self, token: str) -> ResolvedServiceApiCredential | None: ...


class ServiceApiAdmissionScope(Protocol):
    @property
    def snapshot(self) -> ServiceApiAdmissionSnapshot | None: ...

    def create_end_user(self, *, external_user_id: str) -> ServiceApiEndUserIdentity: ...


class ServiceApiAdmissionRepository(Protocol):
    def open(
        self,
        *,
        app_id: str,
        end_user_external_id: str | None,
        require_tenant_owner: bool,
    ) -> AbstractContextManager[ServiceApiAdmissionScope]: ...


class ServiceApiAdmissionFailure(StrEnum):
    TOKEN_INVALID = auto()
    END_USER_REQUIRED = auto()
    APP_NOT_FOUND = auto()
    APP_STATUS_ABNORMAL = auto()
    APP_API_DISABLED = auto()
    TENANT_NOT_FOUND = auto()
    TENANT_ARCHIVED = auto()
    TENANT_OWNER_NOT_FOUND = auto()


class ServiceApiAdmissionError(ValueError):
    def __init__(self, failure: ServiceApiAdmissionFailure) -> None:
        super().__init__(failure)
        self.failure = failure


class ServiceApiAdmissionService:
    def __init__(
        self,
        *,
        tokens: ServiceApiTokenGateway,
        admissions: ServiceApiAdmissionRepository,
    ) -> None:
        self._tokens = tokens
        self._admissions = admissions

    def admit(
        self,
        *,
        token: str,
        requirement: ServiceApiAdmissionRequirement,
        end_user_external_id: str | None,
    ) -> ServiceApiRequestContext:
        credential = self._tokens.resolve(token)
        if credential is None:
            raise ServiceApiAdmissionError(ServiceApiAdmissionFailure.TOKEN_INVALID)

        end_user_requirement = requirement.end_user
        if end_user_requirement is not None and end_user_requirement.required and not end_user_external_id:
            raise ServiceApiAdmissionError(ServiceApiAdmissionFailure.END_USER_REQUIRED)

        normalized_end_user_id = None
        if end_user_requirement is not None:
            normalized_end_user_id = end_user_external_id or "DEFAULT-USER"

        with self._admissions.open(
            app_id=credential.app_id,
            end_user_external_id=normalized_end_user_id,
            require_tenant_owner=requirement.require_tenant_owner,
        ) as admission:
            snapshot = admission.snapshot
            if snapshot is None:
                raise ServiceApiAdmissionError(ServiceApiAdmissionFailure.APP_NOT_FOUND)
            if credential.tenant_id is not None and credential.tenant_id != snapshot.tenant_id:
                raise ServiceApiAdmissionError(ServiceApiAdmissionFailure.TOKEN_INVALID)
            if snapshot.app_status != "normal":
                raise ServiceApiAdmissionError(ServiceApiAdmissionFailure.APP_STATUS_ABNORMAL)
            if not snapshot.api_enabled:
                raise ServiceApiAdmissionError(ServiceApiAdmissionFailure.APP_API_DISABLED)
            if snapshot.tenant_status is None:
                raise ServiceApiAdmissionError(ServiceApiAdmissionFailure.TENANT_NOT_FOUND)
            if snapshot.tenant_status == "archive":
                raise ServiceApiAdmissionError(ServiceApiAdmissionFailure.TENANT_ARCHIVED)
            if requirement.require_tenant_owner and not snapshot.tenant_owner_exists:
                raise ServiceApiAdmissionError(ServiceApiAdmissionFailure.TENANT_OWNER_NOT_FOUND)

            end_user = snapshot.end_user
            if normalized_end_user_id is not None:
                if end_user is None:
                    end_user = admission.create_end_user(external_user_id=normalized_end_user_id)

            return ServiceApiRequestContext(
                tenant_id=snapshot.tenant_id,
                app_id=snapshot.app_id,
                app_mode=snapshot.app_mode,
                end_user=end_user,
            )
