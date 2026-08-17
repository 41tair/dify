from inspect import unwrap
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import BadRequest

from controllers.service_api.app import completion as completion_module
from controllers.service_api.app import workflow as workflow_module
from core.helper.trace_id_helper import get_trace_session_id
from machinery.context import ServiceApiEndUserIdentity, ServiceApiRequestContext


class _Request:
    def __init__(self, *, headers=None, args=None, json=None, is_json=True):
        self.headers = headers or {}
        self.args = args or {}
        self.json = json
        self.is_json = is_json


def test_trace_session_id_header_query_body_priority_matches_service_api_contract():
    req = _Request(
        headers={"X-Trace-Session-Id": "header"},
        args={"trace_session_id": "query"},
        json={"trace_session_id": "body"},
    )

    assert get_trace_session_id(req) == "header"


def test_trace_session_id_invalid_highest_priority_raises_bad_request():
    req = _Request(
        headers={"X-Trace-Session-Id": "   "},
        args={"trace_session_id": "query"},
        json={"trace_session_id": "body"},
    )

    with pytest.raises(BadRequest):
        get_trace_session_id(req)


def _context() -> ServiceApiRequestContext:
    return ServiceApiRequestContext(
        app_id="app-1",
        tenant_id="tenant-1",
        end_user=ServiceApiEndUserIdentity(id="user-1", external_user_id="session-1"),
    )


def _assert_generate_trace_session_id(mock_generate_service: MagicMock, expected: str) -> None:
    _, kwargs = mock_generate_service.call_args
    assert kwargs["args"]["trace_session_id"] == expected


@patch("controllers.service_api.app.completion.service_api_ns")
def test_chat_api_rejects_invalid_highest_priority_query_trace_session_id_without_generating(
    mock_service_api_ns: MagicMock,
    app: Flask,
):
    payload = {"inputs": {}, "query": "hello", "trace_session_id": "body-session"}
    mock_service_api_ns.payload = payload

    generation = MagicMock()
    with (
        app.test_request_context(
            "/chat-messages?trace_session_id=%20%20%20",
            method="POST",
            json=payload,
        ),
        patch(
            "controllers.service_api.app.completion.application_services",
            return_value=SimpleNamespace(service_api_generation=generation),
        ),
    ):
        with pytest.raises(BadRequest):
            unwrap(completion_module.ChatApi.post)(
                completion_module.ChatApi(),
                _context(),
            )

    generation.generate_chat.assert_not_called()


@patch("controllers.service_api.app.workflow.service_api_ns")
def test_workflow_run_api_rejects_invalid_highest_priority_body_trace_session_id_without_generating(
    mock_service_api_ns: MagicMock,
    app: Flask,
):
    payload = {"inputs": {}, "trace_session_id": 123}
    mock_service_api_ns.payload = payload

    workflows = MagicMock()
    with (
        app.test_request_context("/workflows/run", method="POST", json=payload),
        patch(
            "controllers.service_api.app.workflow.application_services",
            return_value=SimpleNamespace(service_api_workflows=workflows),
        ),
    ):
        with pytest.raises(BadRequest):
            unwrap(workflow_module.WorkflowRunApi.post)(
                workflow_module.WorkflowRunApi(),
                _context(),
            )

    workflows.run.assert_not_called()


@patch("controllers.service_api.app.completion.helper.compact_generate_response", return_value={"answer": "ok"})
@patch("controllers.service_api.app.completion.service_api_ns")
def test_completion_api_passes_header_trace_session_id_when_body_value_is_invalid_lower_priority(
    mock_service_api_ns: MagicMock,
    mock_compact: MagicMock,
    app: Flask,
):
    payload = {"inputs": {}, "trace_session_id": 123}
    mock_service_api_ns.payload = payload
    generation = MagicMock()
    generation.generate_completion.return_value = "response"

    with (
        app.test_request_context(
            "/completion-messages",
            method="POST",
            json=payload,
            headers={"X-Trace-Session-Id": " header-session "},
        ),
        patch(
            "controllers.service_api.app.completion.application_services",
            return_value=SimpleNamespace(service_api_generation=generation),
        ),
    ):
        response = unwrap(completion_module.CompletionApi.post)(
            completion_module.CompletionApi(),
            _context(),
        )

    assert response == {"answer": "ok"}
    _assert_generate_trace_session_id(generation.generate_completion, "header-session")


@patch("controllers.service_api.app.completion.helper.compact_generate_response", return_value={"answer": "ok"})
@patch("controllers.service_api.app.completion.service_api_ns")
def test_chat_api_passes_query_trace_session_id_when_body_value_is_invalid_lower_priority(
    mock_service_api_ns: MagicMock,
    mock_compact: MagicMock,
    app: Flask,
):
    payload = {"inputs": {}, "query": "hello", "trace_session_id": 123}
    mock_service_api_ns.payload = payload
    generation = MagicMock()
    generation.generate_chat.return_value = "response"

    with (
        app.test_request_context(
            "/chat-messages?trace_session_id=query-session",
            method="POST",
            json=payload,
        ),
        patch(
            "controllers.service_api.app.completion.application_services",
            return_value=SimpleNamespace(service_api_generation=generation),
        ),
    ):
        response = unwrap(completion_module.ChatApi.post)(
            completion_module.ChatApi(),
            _context(),
        )

    assert response == {"answer": "ok"}
    _assert_generate_trace_session_id(generation.generate_chat, "query-session")


@patch("controllers.service_api.app.workflow.helper.compact_generate_response", return_value={"result": "ok"})
@patch("controllers.service_api.app.workflow.service_api_ns")
def test_workflow_run_api_passes_body_trace_session_id(
    mock_service_api_ns: MagicMock,
    mock_compact: MagicMock,
    app: Flask,
):
    payload = {"inputs": {}, "trace_session_id": " body-session "}
    mock_service_api_ns.payload = payload
    workflows = MagicMock()
    workflows.run.return_value = "response"

    with (
        app.test_request_context("/workflows/run", method="POST", json=payload),
        patch(
            "controllers.service_api.app.workflow.application_services",
            return_value=SimpleNamespace(service_api_workflows=workflows),
        ),
    ):
        response = unwrap(workflow_module.WorkflowRunApi.post)(
            workflow_module.WorkflowRunApi(),
            _context(),
        )

    assert response == {"result": "ok"}
    _assert_generate_trace_session_id(workflows.run, "body-session")
