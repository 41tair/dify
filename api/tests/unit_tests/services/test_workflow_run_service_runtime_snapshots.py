from datetime import datetime
from unittest.mock import MagicMock, patch

from core.workflow.runtime.node_execution_runtime_store import (
    NodeExecutionRuntimeSnapshot,
    workflow_node_execution_runtime_store,
)

from core.workflow.enums import WorkflowExecutionStatus
from models import Account, App
from services.workflow_run_service import WorkflowRunService


def test_get_workflow_run_node_executions_reads_runtime_snapshots_when_running() -> None:
    workflow_node_execution_runtime_store.clear_all()
    workflow_node_execution_runtime_store.upsert(
        workflow_run_id="run-1",
        snapshot=NodeExecutionRuntimeSnapshot(
            execution_id="exec-1",
            node_id="node-1",
            node_type="llm",
            title="Node 1",
            index=1,
            status="running",
            elapsed_time=1.2,
            created_at=datetime.now(),
            finished_at=None,
        ),
    )

    run_repo = MagicMock()
    run_repo.get_workflow_run_by_id.return_value = MagicMock(
        id="run-1",
        status=WorkflowExecutionStatus.RUNNING,
    )
    node_repo = MagicMock()

    with patch("services.workflow_run_service.DifyAPIRepositoryFactory") as repo_factory:
        repo_factory.create_api_workflow_run_repository.return_value = run_repo
        repo_factory.create_api_workflow_node_execution_repository.return_value = node_repo
        service = WorkflowRunService(MagicMock())

    app_model = MagicMock(spec=App)
    app_model.id = "app-1"
    app_model.tenant_id = "tenant-1"

    user = MagicMock(spec=Account)
    user.current_tenant_id = "tenant-1"

    results = service.get_workflow_run_node_executions(app_model, "run-1", user)

    node_repo.get_executions_by_workflow_run.assert_not_called()
    assert len(results) == 1
    assert results[0].id == "exec-1"
    assert results[0].status == "running"


def test_get_workflow_run_node_executions_falls_back_to_repository() -> None:
    workflow_node_execution_runtime_store.clear_all()

    run_repo = MagicMock()
    run_repo.get_workflow_run_by_id.return_value = MagicMock(
        id="run-2",
        status=WorkflowExecutionStatus.SUCCEEDED,
    )
    expected = [MagicMock(id="db-exec-1")]
    node_repo = MagicMock()
    node_repo.get_executions_by_workflow_run.return_value = expected

    with patch("services.workflow_run_service.DifyAPIRepositoryFactory") as repo_factory:
        repo_factory.create_api_workflow_run_repository.return_value = run_repo
        repo_factory.create_api_workflow_node_execution_repository.return_value = node_repo
        service = WorkflowRunService(MagicMock())

    app_model = MagicMock(spec=App)
    app_model.id = "app-1"
    app_model.tenant_id = "tenant-1"

    user = MagicMock(spec=Account)
    user.current_tenant_id = "tenant-1"

    results = service.get_workflow_run_node_executions(app_model, "run-2", user)

    node_repo.get_executions_by_workflow_run.assert_called_once()
    assert results == expected
