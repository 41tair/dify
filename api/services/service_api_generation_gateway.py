"""Infrastructure adapter for Service API completion and chat generation."""

from collections.abc import Mapping
from typing import Any, override

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from core.app.entities.app_invoke_entities import InvokeFrom
from machinery.context import ServiceApiRequestContext
from models.model import App, AppMode, EndUser
from services.app_generate_service import AppGenerateService
from services.app_task_service import AppTaskService
from services.conversation_service import ConversationService
from services.service_api_generation_service import (
    ServiceApiGenerationGateway,
)


class DefaultServiceApiGenerationGateway(ServiceApiGenerationGateway):
    def __init__(self, *, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    @staticmethod
    def _load_identity(session: Session, context: ServiceApiRequestContext) -> tuple[App, EndUser]:
        if context.end_user is None:
            raise RuntimeError("Generation requires an EndUser")
        row = session.execute(
            select(App, EndUser)
            .join(EndUser, EndUser.id == context.end_user.id)
            .where(
                App.id == context.app_id,
                App.tenant_id == context.tenant_id,
                EndUser.app_id == context.app_id,
                EndUser.tenant_id == context.tenant_id,
            )
        ).one_or_none()
        if row is None:
            raise RuntimeError("Admitted app or EndUser no longer exists")
        app, end_user = row
        return app, end_user

    def _run_generate(
        self,
        context: ServiceApiRequestContext,
        *,
        args: Mapping[str, Any],
        streaming: bool,
        validate_conversation_id: str | None = None,
    ) -> Any:
        with self._session_factory() as session:
            try:
                app, end_user = self._load_identity(session, context)
                if validate_conversation_id:
                    ConversationService.get_conversation(
                        app_model=app,
                        conversation_id=validate_conversation_id,
                        user=end_user,
                        session=session,
                    )
                response = AppGenerateService.generate(
                    session=session,
                    app_model=app,
                    user=end_user,
                    args=args,
                    invoke_from=InvokeFrom.SERVICE_API,
                    streaming=streaming,
                )
                session.commit()
                return response
            except Exception:
                session.rollback()
                raise

    @override
    def generate_completion(
        self,
        context: ServiceApiRequestContext,
        *,
        args: Mapping[str, Any],
        streaming: bool,
    ) -> Any:
        return self._run_generate(
            context,
            args=args,
            streaming=streaming,
        )

    @override
    def stop_completion(self, context: ServiceApiRequestContext, *, task_id: str) -> None:
        with self._session_factory() as session:
            _, end_user = self._load_identity(session, context)
            AppTaskService.stop_task(
                task_id=task_id,
                invoke_from=InvokeFrom.SERVICE_API,
                user_id=end_user.id,
                app_mode=AppMode.COMPLETION,
            )

    @override
    def generate_chat(
        self,
        context: ServiceApiRequestContext,
        *,
        args: Mapping[str, Any],
        streaming: bool,
        conversation_id: str | None,
    ) -> Any:
        return self._run_generate(
            context,
            args=args,
            streaming=streaming,
            validate_conversation_id=conversation_id,
        )

    @override
    def stop_chat(self, context: ServiceApiRequestContext, *, task_id: str) -> None:
        with self._session_factory() as session:
            _, end_user = self._load_identity(session, context)
            if context.app_mode is None:
                raise RuntimeError("Admitted app mode is missing")
            AppTaskService.stop_task(
                task_id=task_id,
                invoke_from=InvokeFrom.SERVICE_API,
                user_id=end_user.id,
                app_mode=AppMode.value_of(context.app_mode),
            )
