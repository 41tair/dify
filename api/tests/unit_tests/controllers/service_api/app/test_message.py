from inspect import unwrap
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from flask import Flask

from controllers.service_api.app.message import (
    AppGetFeedbacksApi,
    MessageFeedbackApi,
    MessageListApi,
    MessageSuggestedApi,
)
from machinery.context import ServiceApiEndUserIdentity, ServiceApiRequestContext


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


def _install(conversations: MagicMock):
    return patch(
        "controllers.service_api.app.message.application_services",
        return_value=SimpleNamespace(service_api_conversations=conversations),
    )


def test_list_messages_parses_query_and_delegates(flask_app: Flask) -> None:
    conversations = MagicMock()
    conversations.list_messages.return_value = {"limit": 10, "has_more": False, "data": []}
    conversation_id = str(uuid4())

    with flask_app.test_request_context(f"/?conversation_id={conversation_id}&limit=10"), _install(conversations):
        response = unwrap(MessageListApi.get)(MessageListApi(), _context())

    assert response == {"limit": 10, "has_more": False, "data": []}
    conversations.list_messages.assert_called_once_with(
        _context(),
        conversation_id=conversation_id,
        first_id=None,
        limit=10,
    )


def test_submit_feedback_parses_payload(flask_app: Flask) -> None:
    conversations = MagicMock()
    message_id = uuid4()
    payload = {"rating": "like", "content": "helpful"}

    with (
        flask_app.test_request_context("/", method="POST", json=payload),
        patch("controllers.service_api.app.message.service_api_ns") as namespace,
        _install(conversations),
    ):
        namespace.payload = payload
        response = unwrap(MessageFeedbackApi.post)(
            MessageFeedbackApi(),
            _context(),
            message_id,
        )

    assert response == {"result": "success"}
    conversations.submit_feedback.assert_called_once_with(
        _context(),
        message_id=str(message_id),
        rating="like",
        content="helpful",
    )


def test_list_feedbacks_is_an_app_scoped_use_case(flask_app: Flask) -> None:
    conversations = MagicMock()
    conversations.list_feedbacks.return_value = []

    with flask_app.test_request_context("/?page=2&limit=5"), _install(conversations):
        response = unwrap(AppGetFeedbacksApi.get)(AppGetFeedbacksApi(), _context())

    assert response == {"data": []}
    conversations.list_feedbacks.assert_called_once_with(_context(), page=2, limit=5)


def test_suggested_questions_serializes_application_result(flask_app: Flask) -> None:
    conversations = MagicMock()
    conversations.suggested_questions.return_value = ["next question"]
    message_id = uuid4()

    with flask_app.test_request_context("/"), _install(conversations):
        response = unwrap(MessageSuggestedApi.get)(
            MessageSuggestedApi(),
            _context(),
            message_id,
        )

    assert response == {"result": "success", "data": ["next question"]}
    conversations.suggested_questions.assert_called_once_with(
        _context(),
        message_id=str(message_id),
    )
