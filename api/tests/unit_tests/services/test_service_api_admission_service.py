from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import pytest

from machinery.context import ServiceApiEndUserIdentity
from services.entities.service_api_entities import (
    ResolvedServiceApiCredential,
    ServiceApiAdmissionRequirement,
    ServiceApiAdmissionSnapshot,
    ServiceApiEndUserRequirement,
    ServiceApiEndUserSource,
)
from services.service_api_admission_service import (
    ServiceApiAdmissionError,
    ServiceApiAdmissionFailure,
    ServiceApiAdmissionService,
)


class _TokenGateway:
    def __init__(self, credential: ResolvedServiceApiCredential | None) -> None:
        self.credential = credential
        self.tokens: list[str] = []

    def resolve(self, token: str) -> ResolvedServiceApiCredential | None:
        self.tokens.append(token)
        return self.credential


@dataclass
class _AdmissionScope:
    snapshot: ServiceApiAdmissionSnapshot | None
    created_external_user_id: str | None = None

    def create_end_user(self, *, external_user_id: str) -> ServiceApiEndUserIdentity:
        self.created_external_user_id = external_user_id
        return ServiceApiEndUserIdentity(id="end-user-created", external_user_id=external_user_id)


class _AdmissionRepository:
    def __init__(self, scope: _AdmissionScope) -> None:
        self.scope = scope
        self.opened_with: tuple[str, str | None, bool] | None = None

    @contextmanager
    def open(
        self,
        *,
        app_id: str,
        end_user_external_id: str | None,
        require_tenant_owner: bool,
    ) -> Iterator[_AdmissionScope]:
        self.opened_with = (app_id, end_user_external_id, require_tenant_owner)
        yield self.scope


def _snapshot(
    *,
    app_status: str = "normal",
    api_enabled: bool = True,
    tenant_status: str | None = "normal",
    tenant_owner_exists: bool = True,
    end_user: ServiceApiEndUserIdentity | None = None,
) -> ServiceApiAdmissionSnapshot:
    return ServiceApiAdmissionSnapshot(
        app_id="app-1",
        tenant_id="tenant-1",
        app_mode="chat",
        app_status=app_status,
        api_enabled=api_enabled,
        tenant_status=tenant_status,
        tenant_owner_exists=tenant_owner_exists,
        end_user=end_user,
    )


_DEFAULT_CREDENTIAL = ResolvedServiceApiCredential(
    app_id="app-1",
    tenant_id="tenant-1",
)


def _service(
    snapshot: ServiceApiAdmissionSnapshot | None,
    *,
    credential: ResolvedServiceApiCredential | None = _DEFAULT_CREDENTIAL,
) -> tuple[ServiceApiAdmissionService, _TokenGateway, _AdmissionRepository, _AdmissionScope]:
    tokens = _TokenGateway(credential)
    scope = _AdmissionScope(snapshot)
    admissions = _AdmissionRepository(scope)
    return ServiceApiAdmissionService(tokens=tokens, admissions=admissions), tokens, admissions, scope


@pytest.mark.parametrize(
    ("snapshot", "failure"),
    [
        (None, ServiceApiAdmissionFailure.APP_NOT_FOUND),
        (_snapshot(app_status="abnormal"), ServiceApiAdmissionFailure.APP_STATUS_ABNORMAL),
        (_snapshot(api_enabled=False), ServiceApiAdmissionFailure.APP_API_DISABLED),
        (_snapshot(tenant_status=None), ServiceApiAdmissionFailure.TENANT_NOT_FOUND),
        (_snapshot(tenant_status="archive"), ServiceApiAdmissionFailure.TENANT_ARCHIVED),
        (_snapshot(tenant_owner_exists=False), ServiceApiAdmissionFailure.TENANT_OWNER_NOT_FOUND),
    ],
)
def test_admit_rejects_invalid_app_state(
    snapshot: ServiceApiAdmissionSnapshot | None,
    failure: ServiceApiAdmissionFailure,
) -> None:
    service, _, _, _ = _service(snapshot)

    with pytest.raises(ServiceApiAdmissionError) as error:
        service.admit(
            token="token",
            requirement=ServiceApiAdmissionRequirement(),
            end_user_external_id=None,
        )

    assert error.value.failure == failure


def test_admit_rejects_invalid_token_without_opening_repository() -> None:
    service, tokens, admissions, _ = _service(_snapshot(), credential=None)

    with pytest.raises(ServiceApiAdmissionError) as error:
        service.admit(
            token="invalid",
            requirement=ServiceApiAdmissionRequirement(),
            end_user_external_id=None,
        )

    assert error.value.failure == ServiceApiAdmissionFailure.TOKEN_INVALID
    assert tokens.tokens == ["invalid"]
    assert admissions.opened_with is None


def test_admit_rejects_token_tenant_mismatch() -> None:
    service, _, _, _ = _service(
        _snapshot(),
        credential=ResolvedServiceApiCredential(app_id="app-1", tenant_id="tenant-other"),
    )

    with pytest.raises(ServiceApiAdmissionError) as error:
        service.admit(
            token="token",
            requirement=ServiceApiAdmissionRequirement(),
            end_user_external_id=None,
        )

    assert error.value.failure == ServiceApiAdmissionFailure.TOKEN_INVALID


def test_admit_returns_minimal_stable_context_for_app_only_request() -> None:
    service, _, admissions, scope = _service(_snapshot())

    context = service.admit(
        token="token",
        requirement=ServiceApiAdmissionRequirement(),
        end_user_external_id=None,
    )

    assert context.tenant_id == "tenant-1"
    assert context.app_id == "app-1"
    assert context.app_mode == "chat"
    assert context.end_user is None
    assert admissions.opened_with == ("app-1", None, True)
    assert scope.created_external_user_id is None


def test_admit_creates_required_end_user_in_admission_scope() -> None:
    service, _, admissions, scope = _service(_snapshot())
    requirement = ServiceApiAdmissionRequirement(
        end_user=ServiceApiEndUserRequirement(source=ServiceApiEndUserSource.JSON, required=True)
    )

    context = service.admit(
        token="token",
        requirement=requirement,
        end_user_external_id="external-1",
    )

    assert admissions.opened_with == ("app-1", "external-1", True)
    assert scope.created_external_user_id == "external-1"
    assert context.end_user == ServiceApiEndUserIdentity(
        id="end-user-created",
        external_user_id="external-1",
    )


def test_admit_uses_default_user_only_when_endpoint_declares_end_user() -> None:
    service, _, admissions, scope = _service(_snapshot())
    requirement = ServiceApiAdmissionRequirement(
        end_user=ServiceApiEndUserRequirement(source=ServiceApiEndUserSource.QUERY)
    )

    context = service.admit(
        token="token",
        requirement=requirement,
        end_user_external_id=None,
    )

    assert admissions.opened_with == ("app-1", "DEFAULT-USER", True)
    assert scope.created_external_user_id == "DEFAULT-USER"
    assert context.end_user is not None


def test_admit_reuses_existing_identity_without_mutating_its_creation_source() -> None:
    identity = ServiceApiEndUserIdentity(id="end-user-1", external_user_id="external-1")
    service, _, _, scope = _service(_snapshot(end_user=identity))

    context = service.admit(
        token="token",
        requirement=ServiceApiAdmissionRequirement(
            end_user=ServiceApiEndUserRequirement(source=ServiceApiEndUserSource.FORM)
        ),
        end_user_external_id="external-1",
    )

    assert context.end_user == identity
    assert scope.created_external_user_id is None


def test_admit_validates_required_user_before_database_access() -> None:
    service, _, admissions, _ = _service(_snapshot())

    with pytest.raises(ServiceApiAdmissionError) as error:
        service.admit(
            token="token",
            requirement=ServiceApiAdmissionRequirement(
                end_user=ServiceApiEndUserRequirement(
                    source=ServiceApiEndUserSource.JSON,
                    required=True,
                )
            ),
            end_user_external_id=None,
        )

    assert error.value.failure == ServiceApiAdmissionFailure.END_USER_REQUIRED
    assert admissions.opened_with is None
