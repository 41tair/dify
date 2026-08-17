"""Application service for Service API completion and chat generation."""

from collections.abc import Mapping
from typing import Any, Protocol

from machinery.context import ServiceApiRequestContext
from services.service_api_workflow_version_policy import ServiceApiWorkflowVersionPolicy

_CHAT_MODES = {"chat", "agent-chat", "advanced-chat", "agent"}


class ServiceApiGenerationAppUnavailableError(ValueError):
    pass


class ServiceApiGenerationNotChatAppError(ValueError):
    pass


class ServiceApiAgentStreamingOnlyError(ValueError):
    pass


class ServiceApiWorkflowVersionNotAllowedError(ValueError):
    pass


class ServiceApiGenerationGateway(Protocol):
    def generate_completion(
        self,
        context: ServiceApiRequestContext,
        *,
        args: Mapping[str, Any],
        streaming: bool,
    ) -> Any: ...

    def stop_completion(self, context: ServiceApiRequestContext, *, task_id: str) -> None: ...

    def generate_chat(
        self,
        context: ServiceApiRequestContext,
        *,
        args: Mapping[str, Any],
        streaming: bool,
        conversation_id: str | None,
    ) -> Any: ...

    def stop_chat(self, context: ServiceApiRequestContext, *, task_id: str) -> None: ...


class ServiceApiGenerationService:
    def __init__(
        self,
        *,
        generation: ServiceApiGenerationGateway,
        workflow_versions: ServiceApiWorkflowVersionPolicy,
    ) -> None:
        self._generation = generation
        self._workflow_versions = workflow_versions

    @staticmethod
    def _require_mode(context: ServiceApiRequestContext, allowed_modes: set[str], error: type[ValueError]) -> None:
        if context.app_mode not in allowed_modes:
            raise error()

    def generate_completion(
        self,
        context: ServiceApiRequestContext,
        *,
        args: Mapping[str, Any],
        streaming: bool,
    ) -> Any:
        self._require_mode(context, {"completion"}, ServiceApiGenerationAppUnavailableError)
        return self._generation.generate_completion(context, args=args, streaming=streaming)

    def stop_completion(self, context: ServiceApiRequestContext, *, task_id: str) -> None:
        self._require_mode(context, {"completion"}, ServiceApiGenerationAppUnavailableError)
        self._generation.stop_completion(context, task_id=task_id)

    def generate_chat(
        self,
        context: ServiceApiRequestContext,
        *,
        args: Mapping[str, Any],
        response_mode: str | None,
        workflow_id: str | None,
        conversation_id: str | None,
    ) -> Any:
        self._require_mode(context, _CHAT_MODES, ServiceApiGenerationNotChatAppError)
        if (
            context.app_mode == "advanced-chat"
            and workflow_id
            and not self._workflow_versions.can_execute_specific_version(tenant_id=context.tenant_id)
        ):
            raise ServiceApiWorkflowVersionNotAllowedError()
        if context.app_mode == "agent":
            if response_mode == "blocking":
                raise ServiceApiAgentStreamingOnlyError()
            streaming = True
        else:
            streaming = response_mode == "streaming"

        return self._generation.generate_chat(
            context,
            args=args,
            streaming=streaming,
            conversation_id=conversation_id,
        )

    def stop_chat(self, context: ServiceApiRequestContext, *, task_id: str) -> None:
        self._require_mode(context, _CHAT_MODES, ServiceApiGenerationNotChatAppError)
        self._generation.stop_chat(context, task_id=task_id)
