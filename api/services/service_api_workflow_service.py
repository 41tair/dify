"""Application service for Service API workflow use cases."""

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any, Protocol

from machinery.context import ServiceApiRequestContext
from services.service_api_workflow_version_policy import ServiceApiWorkflowVersionPolicy

_WORKFLOW_CAPABLE_MODES = {"workflow", "advanced-chat"}


class ServiceApiNotWorkflowAppError(ValueError):
    pass


class ServiceApiWorkflowRunNotFoundError(ValueError):
    pass


class ServiceApiWorkflowVersionNotAllowedError(ValueError):
    pass


class ServiceApiWorkflowGateway(Protocol):
    def get_run(self, context: ServiceApiRequestContext, *, workflow_run_id: str) -> dict[str, Any]: ...

    def run(
        self,
        context: ServiceApiRequestContext,
        *,
        args: Mapping[str, Any],
        streaming: bool,
    ) -> Any: ...

    def stop(self, context: ServiceApiRequestContext, *, task_id: str) -> None: ...

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
    ) -> dict[str, Any]: ...

    def stream_events(
        self,
        context: ServiceApiRequestContext,
        *,
        task_id: str,
        include_state_snapshot: bool,
        continue_on_pause: bool,
    ) -> Iterable[str]: ...


class ServiceApiWorkflowService:
    def __init__(
        self,
        *,
        workflows: ServiceApiWorkflowGateway,
        workflow_versions: ServiceApiWorkflowVersionPolicy,
    ) -> None:
        self._workflows = workflows
        self._workflow_versions = workflow_versions

    @staticmethod
    def _require_mode(context: ServiceApiRequestContext, allowed_modes: set[str]) -> None:
        if context.app_mode not in allowed_modes:
            raise ServiceApiNotWorkflowAppError()

    def get_run(self, context: ServiceApiRequestContext, *, workflow_run_id: str) -> dict[str, Any]:
        self._require_mode(context, _WORKFLOW_CAPABLE_MODES)
        return self._workflows.get_run(context, workflow_run_id=workflow_run_id)

    def run(
        self,
        context: ServiceApiRequestContext,
        *,
        args: Mapping[str, Any],
        streaming: bool,
        workflow_id: str | None,
    ) -> Any:
        self._require_mode(context, {"workflow"})
        if workflow_id and not self._workflow_versions.can_execute_specific_version(tenant_id=context.tenant_id):
            raise ServiceApiWorkflowVersionNotAllowedError()
        return self._workflows.run(
            context,
            args=args,
            streaming=streaming,
        )

    def stop(self, context: ServiceApiRequestContext, *, task_id: str) -> None:
        self._require_mode(context, {"workflow"})
        self._workflows.stop(context, task_id=task_id)

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
        self._require_mode(context, _WORKFLOW_CAPABLE_MODES)
        return self._workflows.list_logs(
            context,
            keyword=keyword,
            status=status,
            created_at_before=created_at_before,
            created_at_after=created_at_after,
            page=page,
            limit=limit,
            created_by_end_user_session_id=created_by_end_user_session_id,
            created_by_account=created_by_account,
        )

    def stream_events(
        self,
        context: ServiceApiRequestContext,
        *,
        task_id: str,
        include_state_snapshot: bool,
        continue_on_pause: bool,
    ) -> Iterable[str]:
        self._require_mode(context, _WORKFLOW_CAPABLE_MODES)
        return self._workflows.stream_events(
            context,
            task_id=task_id,
            include_state_snapshot=include_state_snapshot,
            continue_on_pause=continue_on_pause,
        )
