"""Application service for Service API conversation and message use cases."""

from typing import Any, Protocol

from machinery.context import ServiceApiRequestContext

_CHAT_MODES = {"chat", "agent-chat", "advanced-chat", "agent"}
_VARIABLE_MODES = {"chat", "agent-chat", "advanced-chat"}


class ServiceApiNotChatAppError(ValueError):
    pass


class ServiceApiConversationGateway(Protocol):
    def list_conversations(
        self,
        context: ServiceApiRequestContext,
        *,
        last_id: str | None,
        limit: int,
        sort_by: str,
    ) -> dict[str, Any]: ...

    def delete_conversation(self, context: ServiceApiRequestContext, *, conversation_id: str) -> None: ...

    def rename_conversation(
        self,
        context: ServiceApiRequestContext,
        *,
        conversation_id: str,
        name: str | None,
        auto_generate: bool,
    ) -> dict[str, Any]: ...

    def list_variables(
        self,
        context: ServiceApiRequestContext,
        *,
        conversation_id: str,
        limit: int,
        last_id: str | None,
        variable_name: str | None,
    ) -> dict[str, Any]: ...

    def update_variable(
        self,
        context: ServiceApiRequestContext,
        *,
        conversation_id: str,
        variable_id: str,
        value: Any,
    ) -> dict[str, Any]: ...

    def list_messages(
        self,
        context: ServiceApiRequestContext,
        *,
        conversation_id: str,
        first_id: str | None,
        limit: int,
    ) -> dict[str, Any]: ...

    def submit_feedback(
        self,
        context: ServiceApiRequestContext,
        *,
        message_id: str,
        rating: str | None,
        content: str | None,
    ) -> None: ...

    def list_feedbacks(
        self,
        context: ServiceApiRequestContext,
        *,
        page: int,
        limit: int,
    ) -> list[dict[str, Any]]: ...

    def suggested_questions(self, context: ServiceApiRequestContext, *, message_id: str) -> list[str]: ...


class ServiceApiConversationService:
    def __init__(self, *, conversations: ServiceApiConversationGateway) -> None:
        self._conversations = conversations

    @staticmethod
    def _require_mode(context: ServiceApiRequestContext, allowed_modes: set[str]) -> None:
        if context.app_mode not in allowed_modes:
            raise ServiceApiNotChatAppError()

    def list_conversations(
        self,
        context: ServiceApiRequestContext,
        *,
        last_id: str | None,
        limit: int,
        sort_by: str,
    ) -> dict[str, Any]:
        self._require_mode(context, _CHAT_MODES)
        return self._conversations.list_conversations(context, last_id=last_id, limit=limit, sort_by=sort_by)

    def delete_conversation(self, context: ServiceApiRequestContext, *, conversation_id: str) -> None:
        self._require_mode(context, _CHAT_MODES)
        self._conversations.delete_conversation(context, conversation_id=conversation_id)

    def rename_conversation(
        self,
        context: ServiceApiRequestContext,
        *,
        conversation_id: str,
        name: str | None,
        auto_generate: bool,
    ) -> dict[str, Any]:
        self._require_mode(context, _CHAT_MODES)
        return self._conversations.rename_conversation(
            context,
            conversation_id=conversation_id,
            name=name,
            auto_generate=auto_generate,
        )

    def list_variables(
        self,
        context: ServiceApiRequestContext,
        *,
        conversation_id: str,
        limit: int,
        last_id: str | None,
        variable_name: str | None,
    ) -> dict[str, Any]:
        self._require_mode(context, _VARIABLE_MODES)
        return self._conversations.list_variables(
            context,
            conversation_id=conversation_id,
            limit=limit,
            last_id=last_id,
            variable_name=variable_name,
        )

    def update_variable(
        self,
        context: ServiceApiRequestContext,
        *,
        conversation_id: str,
        variable_id: str,
        value: Any,
    ) -> dict[str, Any]:
        self._require_mode(context, _VARIABLE_MODES)
        return self._conversations.update_variable(
            context,
            conversation_id=conversation_id,
            variable_id=variable_id,
            value=value,
        )

    def list_messages(
        self,
        context: ServiceApiRequestContext,
        *,
        conversation_id: str,
        first_id: str | None,
        limit: int,
    ) -> dict[str, Any]:
        self._require_mode(context, _CHAT_MODES)
        return self._conversations.list_messages(
            context,
            conversation_id=conversation_id,
            first_id=first_id,
            limit=limit,
        )

    def submit_feedback(
        self,
        context: ServiceApiRequestContext,
        *,
        message_id: str,
        rating: str | None,
        content: str | None,
    ) -> None:
        self._conversations.submit_feedback(
            context,
            message_id=message_id,
            rating=rating,
            content=content,
        )

    def list_feedbacks(
        self,
        context: ServiceApiRequestContext,
        *,
        page: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        return self._conversations.list_feedbacks(context, page=page, limit=limit)

    def suggested_questions(self, context: ServiceApiRequestContext, *, message_id: str) -> list[str]:
        self._require_mode(context, _CHAT_MODES)
        return self._conversations.suggested_questions(context, message_id=message_id)
