from inspect import unwrap
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from flask import Flask
from pydantic import ValidationError

from controllers.service_api.app.conversation import (
    ConversationApi,
    ConversationDetailApi,
    ConversationRenameApi,
    ConversationVariableDetailApi,
    ConversationVariablesApi,
    ConversationVariablesQuery,
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
        "controllers.service_api.app.conversation.application_services",
        return_value=SimpleNamespace(service_api_conversations=conversations),
    )


def test_variable_query_rejects_unsafe_names() -> None:
    assert ConversationVariablesQuery.model_validate({"variable_name": "safe_name-1"}).variable_name == "safe_name-1"
    with pytest.raises(ValidationError, match="Variable name can only contain"):
        ConversationVariablesQuery.model_validate({"variable_name": "name;drop"})


def test_list_conversations_parses_cursor_query(flask_app: Flask) -> None:
    conversations = MagicMock()
    conversations.list_conversations.return_value = {"limit": 5, "has_more": False, "data": []}

    with flask_app.test_request_context("/?limit=5&sort_by=created_at"), _install(conversations):
        response = unwrap(ConversationApi.get)(ConversationApi(), _context())

    assert response == {"limit": 5, "has_more": False, "data": []}
    conversations.list_conversations.assert_called_once_with(
        _context(),
        last_id=None,
        limit=5,
        sort_by="created_at",
    )


def test_delete_conversation_delegates_to_application_service(flask_app: Flask) -> None:
    conversations = MagicMock()
    conversation_id = uuid4()

    with flask_app.test_request_context("/", method="DELETE"), _install(conversations):
        response = unwrap(ConversationDetailApi.delete)(
            ConversationDetailApi(),
            _context(),
            conversation_id,
        )

    assert response == ("", 204)
    conversations.delete_conversation.assert_called_once_with(
        _context(),
        conversation_id=str(conversation_id),
    )


def test_rename_conversation_parses_payload(flask_app: Flask) -> None:
    conversations = MagicMock()
    conversations.rename_conversation.return_value = {
        "id": "conversation-1",
        "name": "renamed",
        "inputs": {},
        "status": "normal",
    }
    conversation_id = uuid4()
    payload = {"name": "renamed", "auto_generate": False}

    with (
        flask_app.test_request_context("/", method="POST", json=payload),
        patch("controllers.service_api.app.conversation.service_api_ns") as namespace,
        _install(conversations),
    ):
        namespace.payload = payload
        response = unwrap(ConversationRenameApi.post)(
            ConversationRenameApi(),
            _context(),
            conversation_id,
        )

    assert response["name"] == "renamed"
    conversations.rename_conversation.assert_called_once_with(
        _context(),
        conversation_id=str(conversation_id),
        name="renamed",
        auto_generate=False,
    )


def test_list_and_update_variables_delegate_plain_values(flask_app: Flask) -> None:
    conversations = MagicMock()
    conversations.list_variables.return_value = {"limit": 20, "has_more": False, "data": []}
    conversations.update_variable.return_value = {
        "id": "variable-1",
        "name": "topic",
        "value_type": "string",
        "value": "new value",
    }
    conversation_id = uuid4()
    variable_id = uuid4()

    with flask_app.test_request_context("/?variable_name=topic"), _install(conversations):
        listed = unwrap(ConversationVariablesApi.get)(
            ConversationVariablesApi(),
            _context(),
            conversation_id,
        )

    payload = {"value": "new value"}
    with (
        flask_app.test_request_context("/", method="PUT", json=payload),
        patch("controllers.service_api.app.conversation.service_api_ns") as namespace,
        _install(conversations),
    ):
        namespace.payload = payload
        updated = unwrap(ConversationVariableDetailApi.put)(
            ConversationVariableDetailApi(),
            _context(),
            conversation_id,
            variable_id,
        )

    assert listed == {"limit": 20, "has_more": False, "data": []}
    assert updated["value"] == "new value"
    conversations.list_variables.assert_called_once_with(
        _context(),
        conversation_id=str(conversation_id),
        limit=20,
        last_id=None,
        variable_name="topic",
    )
    conversations.update_variable.assert_called_once_with(
        _context(),
        conversation_id=str(conversation_id),
        variable_id=str(variable_id),
        value="new value",
    )
