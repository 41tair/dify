"""Controller tests for Service API application definitions."""

from inspect import unwrap
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask

from controllers.service_api.app import app as app_controller
from controllers.service_api.app.app import AppInfoApi, AppMetaApi, AppParameterApi
from controllers.service_api.app.error import AgentNotPublishedError, AppUnavailableError
from core.app.app_config.common.parameters_mapping import get_parameters_from_feature_dict
from machinery.context import ServiceApiRequestContext
from models.model import AppMode
from services.app_definition_query_service import (
    AppDefinitionNotPublishedError,
    AppDefinitionSummary,
    AppDefinitionUnavailableError,
)


@pytest.fixture
def flask_app() -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def request_context() -> ServiceApiRequestContext:
    return ServiceApiRequestContext(
        tenant_id="tenant-1",
        app_id="app-1",
        app_mode=AppMode.CHAT.value,
    )


def _install_app_definitions(monkeypatch: pytest.MonkeyPatch) -> Mock:
    app_definitions = Mock()
    monkeypatch.setattr(
        app_controller,
        "application_services",
        Mock(return_value=SimpleNamespace(app_definitions=app_definitions)),
    )
    return app_definitions


def test_get_parameters_delegates_with_admitted_app_id(
    flask_app: Flask,
    request_context: ServiceApiRequestContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_definitions = _install_app_definitions(monkeypatch)
    app_definitions.get_public_parameters.return_value = get_parameters_from_feature_dict(
        features_dict={"opening_statement": "Hello"},
        user_input_form=[],
    )

    with flask_app.test_request_context("/parameters"):
        response = unwrap(AppParameterApi.get)(AppParameterApi(), request_context)

    app_definitions.get_public_parameters.assert_called_once_with(request_context.app_id)
    assert response["opening_statement"] == "Hello"


@pytest.mark.parametrize(
    ("service_error", "http_error"),
    [
        pytest.param(AppDefinitionNotPublishedError(), AgentNotPublishedError, id="not-published"),
        pytest.param(AppDefinitionUnavailableError(), AppUnavailableError, id="unavailable"),
    ],
)
def test_get_parameters_maps_query_errors(
    flask_app: Flask,
    request_context: ServiceApiRequestContext,
    monkeypatch: pytest.MonkeyPatch,
    service_error: Exception,
    http_error: type[Exception],
) -> None:
    app_definitions = _install_app_definitions(monkeypatch)
    app_definitions.get_public_parameters.side_effect = service_error

    with flask_app.test_request_context("/parameters"):
        with pytest.raises(http_error):
            unwrap(AppParameterApi.get)(AppParameterApi(), request_context)


def test_get_meta_delegates_with_admitted_app_id(
    flask_app: Flask,
    request_context: ServiceApiRequestContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_definitions = _install_app_definitions(monkeypatch)
    app_definitions.get_tool_icons.return_value = {}

    with flask_app.test_request_context("/meta"):
        response = unwrap(AppMetaApi.get)(AppMetaApi(), request_context)

    app_definitions.get_tool_icons.assert_called_once_with(request_context.app_id)
    assert response == {"tool_icons": {}}


def test_get_meta_maps_unavailable_definition(
    flask_app: Flask,
    request_context: ServiceApiRequestContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_definitions = _install_app_definitions(monkeypatch)
    app_definitions.get_tool_icons.side_effect = AppDefinitionUnavailableError

    with flask_app.test_request_context("/meta"):
        with pytest.raises(AppUnavailableError):
            unwrap(AppMetaApi.get)(AppMetaApi(), request_context)


def test_get_info_delegates_with_admitted_app_id(
    flask_app: Flask,
    request_context: ServiceApiRequestContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_definitions = _install_app_definitions(monkeypatch)
    app_definitions.get_summary.return_value = AppDefinitionSummary(
        name="Test App",
        description="A test application",
        tags=("test-tag",),
        mode=AppMode.CHAT.value,
        author_name="Test Author",
    )

    with flask_app.test_request_context("/info"):
        response = unwrap(AppInfoApi.get)(AppInfoApi(), request_context)

    app_definitions.get_summary.assert_called_once_with(request_context.app_id)
    assert response == {
        "name": "Test App",
        "description": "A test application",
        "tags": ["test-tag"],
        "mode": AppMode.CHAT.value,
        "author_name": "Test Author",
    }


def test_get_info_maps_unavailable_app(
    flask_app: Flask,
    request_context: ServiceApiRequestContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_definitions = _install_app_definitions(monkeypatch)
    app_definitions.get_summary.side_effect = AppDefinitionUnavailableError()

    with flask_app.test_request_context("/info"):
        with pytest.raises(AppUnavailableError):
            unwrap(AppInfoApi.get)(AppInfoApi(), request_context)
