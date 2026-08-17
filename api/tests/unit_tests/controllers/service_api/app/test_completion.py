from inspect import unwrap
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from flask import Flask
from pydantic import ValidationError
from werkzeug.exceptions import BadRequest

from controllers.service_api.app.completion import (
    ChatApi,
    ChatRequestPayload,
    ChatStopApi,
    CompletionApi,
    CompletionRequestPayload,
    CompletionStopApi,
)
from machinery.context import ServiceApiEndUserIdentity, ServiceApiRequestContext
from services.service_api_generation_service import ServiceApiAgentStreamingOnlyError


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


def _install(generation: MagicMock):
    return patch(
        "controllers.service_api.app.completion.application_services",
        return_value=SimpleNamespace(service_api_generation=generation),
    )


def test_request_contracts_validate_conversation_id() -> None:
    assert CompletionRequestPayload.model_validate({"inputs": {}}).response_mode is None
    blank_conversation = ChatRequestPayload.model_validate(
        {"inputs": {}, "query": "hello", "conversation_id": ""}
    )
    assert blank_conversation.conversation_id is None
    with pytest.raises(ValidationError, match="conversation_id must be a valid UUID"):
        ChatRequestPayload.model_validate({"inputs": {}, "query": "hello", "conversation_id": "invalid"})


def test_completion_parses_transport_metadata_and_calls_generation_use_case(flask_app: Flask) -> None:
    generation = MagicMock()
    generation.generate_completion.return_value = "generated"
    payload = {"inputs": {"topic": "architecture"}, "query": "hello", "response_mode": "streaming"}

    with (
        flask_app.test_request_context(
            "/",
            method="POST",
            json=payload,
            headers={"X-Trace-Session-Id": "trace-1", "X-External-Trace-Id": "external-trace"},
        ),
        patch("controllers.service_api.app.completion.service_api_ns") as namespace,
        patch("controllers.service_api.app.completion.helper.compact_generate_response", return_value={"ok": True}),
        _install(generation),
    ):
        namespace.payload = payload
        response = unwrap(CompletionApi.post)(CompletionApi(), _context())

    assert response == {"ok": True}
    call = generation.generate_completion.call_args
    assert call.args == (_context(),)
    assert call.kwargs["streaming"] is True
    assert call.kwargs["args"]["auto_generate_name"] is False
    assert call.kwargs["args"]["trace_session_id"] == "trace-1"


def test_chat_passes_only_plain_payload_and_stable_context(flask_app: Flask) -> None:
    generation = MagicMock()
    generation.generate_chat.return_value = "generated"
    conversation_id = str(uuid4())
    payload = {
        "inputs": {},
        "query": "hello",
        "response_mode": "blocking",
        "workflow_id": "workflow-1",
        "conversation_id": conversation_id,
    }

    with (
        flask_app.test_request_context("/", method="POST", json=payload),
        patch("controllers.service_api.app.completion.service_api_ns") as namespace,
        patch("controllers.service_api.app.completion.helper.compact_generate_response", return_value={"ok": True}),
        _install(generation),
    ):
        namespace.payload = payload
        response = unwrap(ChatApi.post)(ChatApi(), _context())

    assert response == {"ok": True}
    generation.generate_chat.assert_called_once()
    call = generation.generate_chat.call_args
    assert call.args == (_context(),)
    assert call.kwargs["response_mode"] == "blocking"
    assert call.kwargs["workflow_id"] == "workflow-1"
    assert call.kwargs["conversation_id"] == conversation_id


def test_chat_maps_application_streaming_policy_error(flask_app: Flask) -> None:
    generation = MagicMock()
    generation.generate_chat.side_effect = ServiceApiAgentStreamingOnlyError()
    payload = {"inputs": {}, "query": "hello", "response_mode": "blocking"}

    with (
        flask_app.test_request_context("/", method="POST", json=payload),
        patch("controllers.service_api.app.completion.service_api_ns") as namespace,
        _install(generation),
    ):
        namespace.payload = payload
        with pytest.raises(BadRequest, match="only supports streaming"):
            unwrap(ChatApi.post)(ChatApi(), _context())


@pytest.mark.parametrize(
    ("resource", "method_name"),
    [(CompletionStopApi, "stop_completion"), (ChatStopApi, "stop_chat")],
)
def test_stop_endpoints_delegate_to_generation_use_case(
    flask_app: Flask,
    resource: type[CompletionStopApi] | type[ChatStopApi],
    method_name: str,
) -> None:
    generation = MagicMock()

    with flask_app.test_request_context("/", method="POST"), _install(generation):
        response, status = unwrap(resource.post)(resource(), _context(), "task-1")

    assert status == 200
    assert response == {"result": "success"}
    getattr(generation, method_name).assert_called_once_with(_context(), task_id="task-1")
