"""Infrastructure adapter for Service API workflow use cases."""

import json
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any, override

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from core.app.apps.advanced_chat.app_generator import AdvancedChatAppGenerator
from core.app.apps.base_app_generator import BaseAppGenerator
from core.app.apps.base_app_queue_manager import AppQueueManager
from core.app.apps.common.workflow_response_converter import WorkflowResponseConverter
from core.app.apps.message_generator import MessageGenerator
from core.app.apps.workflow.app_generator import WorkflowAppGenerator
from core.app.entities.app_invoke_entities import InvokeFrom
from core.app.entities.task_entities import StreamEvent
from core.workflow.human_input_policy import HumanInputSurface
from extensions.ext_redis import RedisClientWrapper
from graphon.enums import WorkflowExecutionStatus
from graphon.graph_engine.manager import GraphEngineManager
from machinery.context import ServiceApiRequestContext
from models import Account
from models.enums import CreatorUserRole
from models.model import App, AppMode, EndUser
from models.workflow import WorkflowRun
from repositories.factory import DifyAPIRepositoryFactory
from services.app_generate_service import AppGenerateService
from services.service_api_workflow_service import (
    ServiceApiWorkflowGateway,
    ServiceApiWorkflowRunNotFoundError,
)
from services.workflow_app_service import WorkflowAppService
from services.workflow_event_snapshot_service import build_workflow_event_stream


class DefaultServiceApiWorkflowGateway(ServiceApiWorkflowGateway):
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        redis: RedisClientWrapper,
    ) -> None:
        self._session_factory = session_factory
        self._redis = redis

    @staticmethod
    def _load_app(session: Session, context: ServiceApiRequestContext) -> App:
        app = session.scalar(
            select(App).where(
                App.id == context.app_id,
                App.tenant_id == context.tenant_id,
            )
        )
        if app is None:
            raise RuntimeError("Admitted app no longer exists")
        return app

    @staticmethod
    def _workflow_run_record(workflow_run: WorkflowRun) -> dict[str, Any]:
        return {
            "id": workflow_run.id,
            "workflow_id": workflow_run.workflow_id,
            "status": workflow_run.status,
            "inputs": workflow_run.inputs,
            "outputs": workflow_run.outputs_dict,
            "error": workflow_run.error,
            "total_steps": workflow_run.total_steps,
            "total_tokens": workflow_run.total_tokens,
            "created_at": workflow_run.created_at,
            "finished_at": workflow_run.finished_at,
            "elapsed_time": workflow_run.elapsed_time,
        }

    @staticmethod
    def _workflow_run_log_record(workflow_run: WorkflowRun | None) -> dict[str, Any] | None:
        if workflow_run is None:
            return None
        return {
            "id": workflow_run.id,
            "version": workflow_run.version,
            "status": workflow_run.status,
            "triggered_from": workflow_run.triggered_from,
            "error": workflow_run.error,
            "elapsed_time": workflow_run.elapsed_time,
            "total_tokens": workflow_run.total_tokens,
            "total_steps": workflow_run.total_steps,
            "created_at": workflow_run.created_at,
            "finished_at": workflow_run.finished_at,
            "exceptions_count": workflow_run.exceptions_count,
        }

    @classmethod
    def _load_workflow_identity(cls, session: Session, context: ServiceApiRequestContext) -> tuple[App, EndUser]:
        if context.end_user is None:
            raise RuntimeError("Workflow execution requires an EndUser")
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

    @override
    def get_run(self, context: ServiceApiRequestContext, *, workflow_run_id: str) -> dict[str, Any]:
        repository = DifyAPIRepositoryFactory.create_api_workflow_run_repository(self._session_factory)
        workflow_run = repository.get_workflow_run_by_id(
            tenant_id=context.tenant_id,
            app_id=context.app_id,
            run_id=workflow_run_id,
        )
        if workflow_run is None:
            raise ServiceApiWorkflowRunNotFoundError()
        return self._workflow_run_record(workflow_run)

    @override
    def run(
        self,
        context: ServiceApiRequestContext,
        *,
        args: Mapping[str, Any],
        streaming: bool,
    ) -> Any:
        with self._session_factory() as session:
            try:
                app, end_user = self._load_workflow_identity(session, context)
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
    def stop(self, context: ServiceApiRequestContext, *, task_id: str) -> None:
        AppQueueManager.set_stop_flag_no_user_check(task_id)
        GraphEngineManager(self._redis).send_stop_command(task_id)

    @override
    def list_logs(
        self,
        context: ServiceApiRequestContext,
        *,
        keyword: str | None,
        status: str | None,
        created_at_before: datetime | None,
        created_at_after: datetime | None,
        page: int,
        limit: int,
        created_by_end_user_session_id: str | None,
        created_by_account: str | None,
    ) -> dict[str, Any]:
        with self._session_factory() as session:
            app = self._load_app(session, context)
            pagination = WorkflowAppService().get_paginate_workflow_app_logs(
                session=session,
                app_model=app,
                keyword=keyword,
                status=WorkflowExecutionStatus(status) if status else None,
                created_at_before=created_at_before,
                created_at_after=created_at_after,
                page=page,
                limit=limit,
                created_by_end_user_session_id=created_by_end_user_session_id,
                created_by_account=created_by_account,
            )
            workflow_runs = DifyAPIRepositoryFactory.create_api_workflow_run_repository(self._session_factory)
            data: list[dict[str, Any]] = []
            for item in pagination["data"]:
                log = item.log
                workflow_run = workflow_runs.get_workflow_run_by_id(
                    tenant_id=context.tenant_id,
                    app_id=context.app_id,
                    run_id=log.workflow_run_id,
                )
                created_by_account_record = None
                created_by_end_user_record = None
                if log.created_by_role == CreatorUserRole.ACCOUNT:
                    account = session.get(Account, log.created_by)
                    if account is not None:
                        created_by_account_record = {
                            "id": account.id,
                            "name": account.name,
                            "email": account.email,
                        }
                elif log.created_by_role == CreatorUserRole.END_USER:
                    end_user = session.get(EndUser, log.created_by)
                    if end_user is not None:
                        created_by_end_user_record = {
                            "id": end_user.id,
                            "type": end_user.type,
                            "is_anonymous": end_user.is_anonymous,
                            "session_id": end_user.session_id,
                        }
                data.append(
                    {
                        "id": log.id,
                        "workflow_run": self._workflow_run_log_record(workflow_run),
                        "details": item.details,
                        "created_from": log.created_from,
                        "created_by_role": log.created_by_role,
                        "created_by_account": created_by_account_record,
                        "created_by_end_user": created_by_end_user_record,
                        "created_at": log.created_at,
                    }
                )
            return {
                "page": pagination["page"],
                "limit": pagination["limit"],
                "total": pagination["total"],
                "has_more": pagination["has_more"],
                "data": data,
            }

    @override
    def stream_events(
        self,
        context: ServiceApiRequestContext,
        *,
        task_id: str,
        include_state_snapshot: bool,
        continue_on_pause: bool,
    ) -> Iterable[str]:
        if context.end_user is None:
            raise RuntimeError("Workflow event access requires an EndUser")
        with self._session_factory() as session:
            app = self._load_app(session, context)
            app_mode = AppMode.value_of(app.mode)
            end_user = session.get(EndUser, context.end_user.id)
            if end_user is None:
                raise RuntimeError("Admitted EndUser no longer exists")

        repository = DifyAPIRepositoryFactory.create_api_workflow_run_repository(self._session_factory)
        workflow_run = repository.get_workflow_run_by_id_and_tenant_id(
            tenant_id=context.tenant_id,
            run_id=task_id,
        )
        if (
            workflow_run is None
            or workflow_run.app_id != context.app_id
            or workflow_run.created_by_role != CreatorUserRole.END_USER
            or workflow_run.created_by != context.end_user.id
        ):
            raise ServiceApiWorkflowRunNotFoundError()

        if workflow_run.finished_at is not None:
            response = WorkflowResponseConverter.workflow_run_result_to_finish_response(
                task_id=workflow_run.id,
                workflow_run=workflow_run,
                creator_user=end_user,
            )
            payload = response.model_dump(mode="json")
            payload["event"] = response.event.value

            def finished_events():
                yield f"data: {json.dumps(payload)}\n\n"

            return finished_events()

        generator: BaseAppGenerator
        if app_mode == AppMode.ADVANCED_CHAT:
            generator = AdvancedChatAppGenerator()
        else:
            generator = WorkflowAppGenerator()
        terminal_events: list[StreamEvent] | None = [] if continue_on_pause else None

        if include_state_snapshot:
            return generator.convert_to_event_stream(
                build_workflow_event_stream(
                    app_mode=app_mode,
                    workflow_run=workflow_run,
                    tenant_id=context.tenant_id,
                    app_id=context.app_id,
                    session_maker=self._session_factory,
                    human_input_surface=HumanInputSurface.SERVICE_API,
                    close_on_pause=not continue_on_pause,
                )
            )
        return generator.convert_to_event_stream(
            MessageGenerator().retrieve_events(
                app_mode,
                workflow_run.id,
                terminal_events=terminal_events,
            )
        )
