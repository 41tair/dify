from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import Forbidden, Unauthorized

from controllers.service_api.flask_admission import service_api_admission
from controllers.service_api.schema import USER_FETCH_FROM_ATTR, USER_REQUIRED_ATTR
from machinery.context import ServiceApiEndUserIdentity, ServiceApiRequestContext
from services.entities.service_api_entities import (
    ServiceApiEndUserRequirement,
    ServiceApiEndUserSource,
)
from services.service_api_admission_service import (
    ServiceApiAdmissionError,
    ServiceApiAdmissionFailure,
)


@pytest.fixture
def flask_app() -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = True
    return app


def _install_admission_service(service: MagicMock):
    return patch(
        "controllers.service_api.flask_admission.application_services",
        return_value=SimpleNamespace(service_api_admission=service),
    )


def test_decorator_injects_stable_context_and_enriches_adapter_observability(flask_app: Flask) -> None:
    context = ServiceApiRequestContext(
        tenant_id="tenant-1",
        app_id="app-1",
        end_user=ServiceApiEndUserIdentity(id="end-user-1", external_user_id="external-1"),
    )
    admission = MagicMock()
    admission.admit.return_value = context

    @service_api_admission(
        end_user=ServiceApiEndUserRequirement(
            source=ServiceApiEndUserSource.JSON,
            required=True,
        )
    )
    def admitted_view(_resource: object, request_context: ServiceApiRequestContext) -> ServiceApiRequestContext:
        return request_context

    with (
        flask_app.test_request_context(
            "/",
            method="POST",
            json={"user": "external-1"},
            headers={"Authorization": "Bearer stable-token"},
        ),
        _install_admission_service(admission),
        patch("controllers.service_api.flask_admission.set_identity_context") as set_log_identity,
        patch("controllers.service_api.flask_admission.enrich_current_span_identity") as set_span_identity,
    ):
        result = admitted_view(object())

    assert result == context
    admission.admit.assert_called_once()
    call = admission.admit.call_args
    assert call.kwargs["token"] == "stable-token"
    assert call.kwargs["end_user_external_id"] == "external-1"
    assert call.kwargs["requirement"].end_user == ServiceApiEndUserRequirement(
        source=ServiceApiEndUserSource.JSON,
        required=True,
    )
    set_log_identity.assert_called_once_with(
        tenant_id="tenant-1",
        user_id="end-user-1",
        user_type="service-api-end-user",
    )
    set_span_identity.assert_called_once_with(
        tenant_id="tenant-1",
        app_id="app-1",
        actor_id="end-user-1",
        actor_type="service-api-end-user",
    )


@pytest.mark.parametrize(
    ("source", "request_kwargs", "expected"),
    [
        (ServiceApiEndUserSource.QUERY, {"query_string": {"user": "query-user"}}, "query-user"),
        (ServiceApiEndUserSource.JSON, {"json": {"user": "json-user"}}, "json-user"),
        (ServiceApiEndUserSource.FORM, {"data": {"user": "form-user"}}, "form-user"),
    ],
)
def test_decorator_parses_end_user_only_in_the_declared_transport_location(
    flask_app: Flask,
    source: ServiceApiEndUserSource,
    request_kwargs: dict[str, object],
    expected: str,
) -> None:
    admission = MagicMock()
    admission.admit.return_value = ServiceApiRequestContext(tenant_id="tenant-1", app_id="app-1")

    @service_api_admission(end_user=ServiceApiEndUserRequirement(source=source))
    def admitted_view(_resource: object, context: ServiceApiRequestContext) -> ServiceApiRequestContext:
        return context

    with (
        flask_app.test_request_context(
            "/",
            method="POST",
            headers={"Authorization": "Bearer token"},
            **request_kwargs,
        ),
        _install_admission_service(admission),
        patch("controllers.service_api.flask_admission.set_identity_context"),
        patch("controllers.service_api.flask_admission.enrich_current_span_identity"),
    ):
        admitted_view(object())

    assert admission.admit.call_args.kwargs["end_user_external_id"] == expected


@pytest.mark.parametrize(
    ("authorization", "message"),
    [
        (None, "Authorization header must be provided"),
        ("Bearer ", "Authorization header must be provided"),
        ("Basic token", "Authorization scheme must be 'Bearer'"),
    ],
)
def test_decorator_rejects_invalid_authorization_header(
    flask_app: Flask,
    authorization: str | None,
    message: str,
) -> None:
    admission = MagicMock()

    @service_api_admission()
    def admitted_view(_resource: object, context: ServiceApiRequestContext) -> ServiceApiRequestContext:
        return context

    headers = {"Authorization": authorization} if authorization is not None else None
    with flask_app.test_request_context("/", headers=headers), _install_admission_service(admission):
        with pytest.raises(Unauthorized, match=message):
            admitted_view(object())

    admission.admit.assert_not_called()


@pytest.mark.parametrize(
    ("failure", "error_type", "message"),
    [
        (ServiceApiAdmissionFailure.TOKEN_INVALID, Unauthorized, "Access token is invalid"),
        (ServiceApiAdmissionFailure.END_USER_REQUIRED, ValueError, "Arg user must be provided"),
        (ServiceApiAdmissionFailure.APP_NOT_FOUND, Forbidden, "app no longer exists"),
        (ServiceApiAdmissionFailure.APP_STATUS_ABNORMAL, Forbidden, "status is abnormal"),
        (ServiceApiAdmissionFailure.APP_API_DISABLED, Forbidden, "API service has been disabled"),
        (ServiceApiAdmissionFailure.TENANT_NOT_FOUND, ValueError, "Tenant does not exist"),
        (ServiceApiAdmissionFailure.TENANT_ARCHIVED, Forbidden, "status is archived"),
        (ServiceApiAdmissionFailure.TENANT_OWNER_NOT_FOUND, Unauthorized, "owner account not found"),
    ],
)
def test_adapter_maps_application_failures_to_transport_errors(
    flask_app: Flask,
    failure: ServiceApiAdmissionFailure,
    error_type: type[Exception],
    message: str,
) -> None:
    admission = MagicMock()
    admission.admit.side_effect = ServiceApiAdmissionError(failure)

    @service_api_admission()
    def admitted_view(_resource: object, context: ServiceApiRequestContext) -> ServiceApiRequestContext:
        return context

    with (
        flask_app.test_request_context("/", headers={"Authorization": "Bearer token"}),
        _install_admission_service(admission),
    ):
        with pytest.raises(error_type, match=message):
            admitted_view(object())


def test_decorator_preserves_restx_documentation_contract() -> None:
    @service_api_admission(
        end_user=ServiceApiEndUserRequirement(
            source=ServiceApiEndUserSource.QUERY,
            required=True,
        )
    )
    def admitted_view(_resource: object, _context: ServiceApiRequestContext) -> None:
        pass

    assert admitted_view.__apidoc__["responses"][403]
    assert admitted_view.__apidoc__["params"]["user"]["required"] is True
    assert getattr(admitted_view, USER_FETCH_FROM_ATTR) == "QUERY"
    assert getattr(admitted_view, USER_REQUIRED_ATTR) is True
