from unittest.mock import MagicMock

import pytest

from machinery.context import ServiceApiRequestContext
from services.service_api_conversation_service import ServiceApiConversationService, ServiceApiNotChatAppError
from services.service_api_generation_service import (
    ServiceApiAgentStreamingOnlyError,
    ServiceApiGenerationNotChatAppError,
    ServiceApiGenerationService,
)
from services.service_api_generation_service import (
    ServiceApiWorkflowVersionNotAllowedError as GenerationWorkflowVersionNotAllowedError,
)
from services.service_api_workflow_service import (
    ServiceApiNotWorkflowAppError,
    ServiceApiWorkflowService,
    ServiceApiWorkflowVersionNotAllowedError,
)


class _WorkflowVersionPolicy:
    def __init__(self, *, allowed: bool) -> None:
        self.allowed = allowed
        self.tenant_ids: list[str] = []

    def can_execute_specific_version(self, *, tenant_id: str) -> bool:
        self.tenant_ids.append(tenant_id)
        return self.allowed


def _context(*, app_mode: str) -> ServiceApiRequestContext:
    return ServiceApiRequestContext(
        tenant_id="tenant-1",
        app_id="app-1",
        app_mode=app_mode,
    )


def test_generation_service_derives_chat_streaming_before_calling_gateway() -> None:
    gateway = MagicMock()
    gateway.generate_chat.return_value = "response"
    service = ServiceApiGenerationService(
        generation=gateway,
        workflow_versions=_WorkflowVersionPolicy(allowed=True),
    )

    result = service.generate_chat(
        _context(app_mode="chat"),
        args={"query": "hello"},
        response_mode="streaming",
        workflow_id=None,
        conversation_id="conversation-1",
    )

    assert result == "response"
    gateway.generate_chat.assert_called_once_with(
        _context(app_mode="chat"),
        args={"query": "hello"},
        streaming=True,
        conversation_id="conversation-1",
    )


def test_generation_service_rejects_invalid_mode_without_calling_gateway() -> None:
    gateway = MagicMock()
    service = ServiceApiGenerationService(
        generation=gateway,
        workflow_versions=_WorkflowVersionPolicy(allowed=True),
    )

    with pytest.raises(ServiceApiGenerationNotChatAppError):
        service.generate_chat(
            _context(app_mode="workflow"),
            args={},
            response_mode="streaming",
            workflow_id=None,
            conversation_id=None,
        )

    gateway.generate_chat.assert_not_called()


def test_generation_service_owns_agent_and_workflow_version_policies() -> None:
    gateway = MagicMock()
    denied_versions = _WorkflowVersionPolicy(allowed=False)
    service = ServiceApiGenerationService(generation=gateway, workflow_versions=denied_versions)

    with pytest.raises(ServiceApiAgentStreamingOnlyError):
        service.generate_chat(
            _context(app_mode="agent"),
            args={},
            response_mode="blocking",
            workflow_id=None,
            conversation_id=None,
        )
    with pytest.raises(GenerationWorkflowVersionNotAllowedError):
        service.generate_chat(
            _context(app_mode="advanced-chat"),
            args={},
            response_mode="streaming",
            workflow_id="workflow-1",
            conversation_id=None,
        )

    assert denied_versions.tenant_ids == ["tenant-1"]
    gateway.generate_chat.assert_not_called()


def test_workflow_service_owns_mode_and_version_policy() -> None:
    gateway = MagicMock()
    denied_versions = _WorkflowVersionPolicy(allowed=False)
    service = ServiceApiWorkflowService(workflows=gateway, workflow_versions=denied_versions)

    with pytest.raises(ServiceApiNotWorkflowAppError):
        service.get_run(_context(app_mode="chat"), workflow_run_id="run-1")
    with pytest.raises(ServiceApiWorkflowVersionNotAllowedError):
        service.run(
            _context(app_mode="workflow"),
            args={},
            streaming=False,
            workflow_id="workflow-1",
        )

    gateway.get_run.assert_not_called()
    gateway.run.assert_not_called()


def test_conversation_service_rejects_non_chat_mode_before_gateway() -> None:
    gateway = MagicMock()
    service = ServiceApiConversationService(conversations=gateway)

    with pytest.raises(ServiceApiNotChatAppError):
        service.list_conversations(
            _context(app_mode="completion"),
            last_id=None,
            limit=20,
            sort_by="-updated_at",
        )

    gateway.list_conversations.assert_not_called()


def test_conversation_service_allows_completion_feedback() -> None:
    gateway = MagicMock()
    service = ServiceApiConversationService(conversations=gateway)
    context = _context(app_mode="completion")

    service.submit_feedback(
        context,
        message_id="message-1",
        rating="like",
        content="helpful",
    )

    gateway.submit_feedback.assert_called_once_with(
        context,
        message_id="message-1",
        rating="like",
        content="helpful",
    )
