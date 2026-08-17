from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from machinery.context import ServiceApiEndUserIdentity, ServiceApiRequestContext
from services.service_api_generation_gateway import DefaultServiceApiGenerationGateway
from services.service_api_workflow_gateway import DefaultServiceApiWorkflowGateway


def _context(*, app_mode: str) -> ServiceApiRequestContext:
    return ServiceApiRequestContext(
        tenant_id="tenant-1",
        app_id="app-1",
        app_mode=app_mode,
        end_user=ServiceApiEndUserIdentity(id="end-user-1", external_user_id="external-1"),
    )


def test_chat_generation_loads_app_and_end_user_once() -> None:
    session_factory = MagicMock()
    session = session_factory.return_value.__enter__.return_value
    gateway = DefaultServiceApiGenerationGateway(session_factory=session_factory)
    app = SimpleNamespace(id="app-1")
    end_user = SimpleNamespace(id="end-user-1")

    with (
        patch.object(gateway, "_load_identity", return_value=(app, end_user)) as load_identity,
        patch("services.service_api_generation_gateway.AppGenerateService.generate", return_value="response"),
    ):
        result = gateway.generate_chat(
            _context(app_mode="chat"),
            args={"query": "hello"},
            streaming=False,
            conversation_id=None,
        )

    assert result == "response"
    load_identity.assert_called_once_with(session, _context(app_mode="chat"))


def test_workflow_stop_does_not_query_app_only_to_recheck_mode() -> None:
    session_factory = MagicMock()
    redis = MagicMock()
    gateway = DefaultServiceApiWorkflowGateway(session_factory=session_factory, redis=redis)

    with (
        patch("services.service_api_workflow_gateway.AppQueueManager.set_stop_flag_no_user_check") as stop_flag,
        patch("services.service_api_workflow_gateway.GraphEngineManager") as graph_engine_manager,
    ):
        gateway.stop(_context(app_mode="workflow"), task_id="task-1")

    session_factory.assert_not_called()
    stop_flag.assert_called_once_with("task-1")
    graph_engine_manager.assert_called_once_with(redis)
    graph_engine_manager.return_value.send_stop_command.assert_called_once_with("task-1")


def test_workflow_run_detail_does_not_query_app_only_to_recheck_mode() -> None:
    session_factory = MagicMock()
    gateway = DefaultServiceApiWorkflowGateway(session_factory=session_factory, redis=MagicMock())
    repository = MagicMock()
    repository.get_workflow_run_by_id.return_value = SimpleNamespace(
        id="run-1",
        workflow_id="workflow-1",
        status="succeeded",
        inputs='{"query": "hello"}',
        outputs_dict={"answer": "done"},
        error=None,
        total_steps=1,
        total_tokens=2,
        created_at=None,
        finished_at=None,
        elapsed_time=0.5,
    )

    with patch(
        "services.service_api_workflow_gateway.DifyAPIRepositoryFactory.create_api_workflow_run_repository",
        return_value=repository,
    ):
        result = gateway.get_run(_context(app_mode="workflow"), workflow_run_id="run-1")

    assert result["inputs"] == '{"query": "hello"}'
    assert result["outputs"] == {"answer": "done"}
    session_factory.assert_not_called()
