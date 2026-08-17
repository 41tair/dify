import json
from inspect import unwrap
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import BadRequest, NotFound

from controllers.service_api.app.human_input_form import WorkflowHumanInputFormApi
from machinery.context import ServiceApiEndUserIdentity, ServiceApiRequestContext
from services.service_api_human_input_service import (
    ServiceApiHumanInputInvalidRecipientError,
    ServiceApiHumanInputNotFoundError,
)


@pytest.fixture
def flask_app() -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = True
    return app


def _context() -> ServiceApiRequestContext:
    return ServiceApiRequestContext(
        tenant_id="tenant-1",
        app_id="app-1",
        end_user=ServiceApiEndUserIdentity(id="end-user-1", external_user_id="external-1"),
    )


def _install(forms: MagicMock):
    return patch(
        "controllers.service_api.app.human_input_form.application_services",
        return_value=SimpleNamespace(service_api_human_inputs=forms),
    )


def test_get_form_serializes_application_result_as_http_response(flask_app: Flask) -> None:
    forms = MagicMock()
    forms.get_form.return_value = {
        "form_content": "Please approve",
        "inputs": [],
        "resolved_default_values": {},
        "user_actions": [],
    }

    with flask_app.test_request_context("/"), _install(forms):
        response = unwrap(WorkflowHumanInputFormApi.get)(
            WorkflowHumanInputFormApi(),
            _context(),
            "form-token",
        )

    assert response.mimetype == "application/json"
    assert json.loads(response.get_data()) == forms.get_form.return_value
    forms.get_form.assert_called_once_with(_context(), form_token="form-token")


def test_submit_form_parses_payload_and_calls_application_service(flask_app: Flask) -> None:
    forms = MagicMock()
    payload = {"action": "approve", "inputs": {"decision": "yes"}}

    with (
        flask_app.test_request_context("/", method="POST", json=payload),
        patch("controllers.service_api.app.human_input_form.service_api_ns") as namespace,
        _install(forms),
    ):
        namespace.payload = payload
        response = unwrap(WorkflowHumanInputFormApi.post)(
            WorkflowHumanInputFormApi(),
            _context(),
            "form-token",
        )

    assert response == ({}, 200)
    forms.submit_form.assert_called_once_with(
        _context(),
        form_token="form-token",
        action="approve",
        inputs={"decision": "yes"},
    )


@pytest.mark.parametrize(
    ("error", "http_error"),
    [
        (ServiceApiHumanInputNotFoundError(), NotFound),
        (ServiceApiHumanInputInvalidRecipientError(), BadRequest),
    ],
)
def test_submit_form_maps_application_errors(
    flask_app: Flask,
    error: ValueError,
    http_error: type[Exception],
) -> None:
    forms = MagicMock()
    forms.submit_form.side_effect = error
    payload = {"action": "approve", "inputs": {}}

    with (
        flask_app.test_request_context("/", method="POST", json=payload),
        patch("controllers.service_api.app.human_input_form.service_api_ns") as namespace,
        _install(forms),
    ):
        namespace.payload = payload
        with pytest.raises(http_error):
            unwrap(WorkflowHumanInputFormApi.post)(
                WorkflowHumanInputFormApi(),
                _context(),
                "form-token",
            )
