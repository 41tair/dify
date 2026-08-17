"""Infrastructure adapter for Service API conversation and message use cases."""

from typing import Any, cast, override

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from core.app.entities.app_invoke_entities import InvokeFrom
from machinery.context import ServiceApiRequestContext
from models.enums import FeedbackRating
from models.model import App, EndUser, Message
from services.conversation_service import ConversationService
from services.message_service import MessageService
from services.service_api_conversation_service import ServiceApiConversationGateway


class SqlAlchemyServiceApiConversationGateway(ServiceApiConversationGateway):
    def __init__(self, *, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    @staticmethod
    def _load_identity(
        session: Session,
        context: ServiceApiRequestContext,
    ) -> tuple[App, EndUser]:
        if context.end_user is None:
            raise RuntimeError("This Service API operation requires an EndUser")
        row = session.execute(
            select(App, EndUser)
            .join(EndUser, EndUser.id == context.end_user.id)
            .where(
                App.id == context.app_id,
                App.tenant_id == context.tenant_id,
                EndUser.tenant_id == context.tenant_id,
                EndUser.app_id == context.app_id,
            )
        ).one_or_none()
        if row is None:
            raise RuntimeError("Admitted app or EndUser no longer exists")
        app, end_user = row
        return app, end_user

    @staticmethod
    def _simple_conversation(conversation, *, session: Session) -> dict[str, Any]:
        return {
            "id": conversation.id,
            "name": conversation.name,
            "inputs": conversation.inputs_with_session(session=session),
            "status": conversation.status,
            "introduction": conversation.introduction,
            "created_at": conversation.created_at,
            "updated_at": conversation.updated_at,
        }

    @staticmethod
    def _message_list_item(message: Message, *, session: Session) -> dict[str, Any]:
        feedback = message.user_feedback_with_session(session=session)
        agent_thoughts = message.agent_thoughts_with_session(session=session)
        return {
            "id": message.id,
            "conversation_id": message.conversation_id,
            "parent_message_id": message.parent_message_id,
            "inputs": message.inputs_with_session(session=session),
            "query": message.query,
            "answer": message.re_sign_file_url_answer,
            "feedback": {"rating": feedback.rating} if feedback is not None else None,
            "retriever_resources": message.retriever_resources or [],
            "created_at": message.created_at,
            "agent_thoughts": [
                {
                    "id": thought.id,
                    "message_chain_id": thought.message_chain_id,
                    "message_id": thought.message_id,
                    "position": thought.position,
                    "thought": thought.thought,
                    "answer": thought.answer,
                    "tool": thought.tool,
                    "tool_labels": thought.tool_labels,
                    "tool_input": thought.tool_input,
                    "created_at": thought.created_at,
                    "observation": thought.observation,
                    "files": thought.files,
                }
                for thought in agent_thoughts
            ],
            "message_files": message.message_files_with_session(session=session),
            "message_tokens": message.message_tokens,
            "answer_tokens": message.answer_tokens,
            "provider_response_latency": message.provider_response_latency,
            "total_price": message.total_price,
            "currency": message.currency,
            "status": message.status,
            "error": message.error,
            "extra_contents": message.extra_contents,
        }

    @override
    def list_conversations(
        self,
        context: ServiceApiRequestContext,
        *,
        last_id: str | None,
        limit: int,
        sort_by: str,
    ) -> dict[str, Any]:
        with self._session_factory() as session:
            app, end_user = self._load_identity(session, context)
            pagination = ConversationService.pagination_by_last_id(
                session=session,
                app_model=app,
                user=end_user,
                last_id=last_id,
                limit=limit,
                invoke_from=InvokeFrom.SERVICE_API,
                sort_by=sort_by,
            )
            data = [self._simple_conversation(item, session=session) for item in pagination.data]
            return {"limit": pagination.limit, "has_more": pagination.has_more, "data": data}

    @override
    def delete_conversation(self, context: ServiceApiRequestContext, *, conversation_id: str) -> None:
        with self._session_factory() as session:
            app, end_user = self._load_identity(session, context)
            ConversationService.delete(app, conversation_id, end_user, session=session)

    @override
    def rename_conversation(
        self,
        context: ServiceApiRequestContext,
        *,
        conversation_id: str,
        name: str | None,
        auto_generate: bool,
    ) -> dict[str, Any]:
        with self._session_factory() as session:
            app, end_user = self._load_identity(session, context)
            conversation = ConversationService.rename(
                app,
                conversation_id,
                end_user,
                name,
                auto_generate,
                session=session,
            )
            return self._simple_conversation(conversation, session=session)

    @override
    def list_variables(
        self,
        context: ServiceApiRequestContext,
        *,
        conversation_id: str,
        limit: int,
        last_id: str | None,
        variable_name: str | None,
    ) -> dict[str, Any]:
        with self._session_factory() as session:
            app, end_user = self._load_identity(session, context)
            pagination = ConversationService.get_conversational_variable(
                app,
                conversation_id,
                end_user,
                limit,
                last_id,
                variable_name,
                session=session,
            )
            return {
                "limit": pagination.limit,
                "has_more": pagination.has_more,
                "data": pagination.data,
            }

    @override
    def update_variable(
        self,
        context: ServiceApiRequestContext,
        *,
        conversation_id: str,
        variable_id: str,
        value: Any,
    ) -> dict[str, Any]:
        with self._session_factory() as session:
            app, end_user = self._load_identity(session, context)
            return ConversationService.update_conversation_variable(
                app,
                conversation_id,
                variable_id,
                end_user,
                value,
                session=session,
            )

    @override
    def list_messages(
        self,
        context: ServiceApiRequestContext,
        *,
        conversation_id: str,
        first_id: str | None,
        limit: int,
    ) -> dict[str, Any]:
        with self._session_factory() as session:
            app, end_user = self._load_identity(session, context)
            pagination = MessageService.pagination_by_first_id(
                app,
                end_user,
                conversation_id,
                first_id,
                limit,
                session=session,
            )
            data = [self._message_list_item(message, session=session) for message in pagination.data]
            return {"limit": pagination.limit, "has_more": pagination.has_more, "data": data}

    @override
    def submit_feedback(
        self,
        context: ServiceApiRequestContext,
        *,
        message_id: str,
        rating: str | None,
        content: str | None,
    ) -> None:
        with self._session_factory() as session:
            app, end_user = self._load_identity(session, context)
            MessageService.create_feedback(
                app_model=app,
                message_id=message_id,
                user=end_user,
                rating=FeedbackRating(rating) if rating else None,
                content=content,
                session=session,
            )

    @override
    def list_feedbacks(
        self,
        context: ServiceApiRequestContext,
        *,
        page: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            app = session.scalar(
                select(App).where(
                    App.id == context.app_id,
                    App.tenant_id == context.tenant_id,
                )
            )
            if app is None:
                raise RuntimeError("Admitted app no longer exists")
            return cast(
                list[dict[str, Any]],
                MessageService.get_all_messages_feedbacks(app, page=page, limit=limit, session=session),
            )

    @override
    def suggested_questions(self, context: ServiceApiRequestContext, *, message_id: str) -> list[str]:
        with self._session_factory() as session:
            app, end_user = self._load_identity(session, context)
            return MessageService.get_suggested_questions_after_answer(
                app_model=app,
                user=end_user,
                message_id=message_id,
                invoke_from=InvokeFrom.SERVICE_API,
                session=session,
            )
