from datetime import UTC, datetime
from inspect import unwrap
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import NotFound

from controllers.service_api.app.workflow import (
    WorkflowAppLogApi,
    WorkflowRunApi,
    WorkflowRunByIdApi,
    WorkflowRunDetailApi,
    WorkflowTaskStopApi,
)
from machinery.context import ServiceApiEndUserIdentity, ServiceApiRequestContext
from services.service_api_workflow_service import ServiceApiWorkflowRunNotFoundError


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


def _install(workflows: MagicMock):
    return patch(
        "controllers.service_api.app.workflow.application_services",
        return_value=SimpleNamespace(service_api_workflows=workflows),
    )


def test_get_run_serializes_shared_response_contract(flask_app: Flask) -> None:
    workflows = MagicMock()
    workflows.get_run.return_value = {
        "id": "run-1",
        "workflow_id": "workflow-1",
        "status": "succeeded",
        "outputs": {"answer": "done"},
    }

    with flask_app.test_request_context("/"), _install(workflows):
        response = unwrap(WorkflowRunDetailApi.get)(
            WorkflowRunDetailApi(),
            _context(),
            "run-1",
        )

    assert response["outputs"] == {"answer": "done"}
    workflows.get_run.assert_called_once_with(_context(), workflow_run_id="run-1")


def test_get_run_maps_application_not_found(flask_app: Flask) -> None:
    workflows = MagicMock()
    workflows.get_run.side_effect = ServiceApiWorkflowRunNotFoundError()

    with (
        flask_app.test_request_context("/"),
        _install(workflows),
        pytest.raises(NotFound, match="Workflow run not found"),
    ):
        unwrap(WorkflowRunDetailApi.get)(WorkflowRunDetailApi(), _context(), "missing")


@pytest.mark.parametrize(
    ("resource", "workflow_id"),
    [(WorkflowRunApi, None), (WorkflowRunByIdApi, "workflow-1")],
)
def test_run_endpoints_parse_payload_and_delegate(
    flask_app: Flask,
    resource: type[WorkflowRunApi] | type[WorkflowRunByIdApi],
    workflow_id: str | None,
) -> None:
    workflows = MagicMock()
    workflows.run.return_value = "generated"
    payload = {"inputs": {"topic": "architecture"}, "response_mode": "streaming"}

    with (
        flask_app.test_request_context(
            "/",
            method="POST",
            json=payload,
            headers={"X-Trace-Session-Id": "trace-1"},
        ),
        patch("controllers.service_api.app.workflow.service_api_ns") as namespace,
        patch("controllers.service_api.app.workflow.helper.compact_generate_response", return_value={"ok": True}),
        _install(workflows),
    ):
        namespace.payload = payload
        if workflow_id is None:
            response = unwrap(resource.post)(resource(), _context())
        else:
            response = unwrap(resource.post)(resource(), _context(), workflow_id)

    assert response == {"ok": True}
    call = workflows.run.call_args
    assert call.args == (_context(),)
    assert call.kwargs["streaming"] is True
    assert call.kwargs["workflow_id"] == workflow_id
    assert call.kwargs["args"]["trace_session_id"] == "trace-1"
    if workflow_id is not None:
        assert call.kwargs["args"]["workflow_id"] == workflow_id


def test_stop_delegates_to_workflow_application_service(flask_app: Flask) -> None:
    workflows = MagicMock()

    with flask_app.test_request_context("/", method="POST"), _install(workflows):
        response = unwrap(WorkflowTaskStopApi.post)(
            WorkflowTaskStopApi(),
            _context(),
            "task-1",
        )

    assert response == {"result": "success"}
    workflows.stop.assert_called_once_with(_context(), task_id="task-1")


def test_list_logs_parses_dates_and_filters(flask_app: Flask) -> None:
    workflows = MagicMock()
    workflows.list_logs.return_value = {"page": 2, "limit": 5, "total": 0, "has_more": False, "data": []}

    with (
        flask_app.test_request_context(
            "/?page=2&limit=5&status=succeeded&created_at__after=2026-01-01T00:00:00Z"
        ),
        _install(workflows),
    ):
        response = unwrap(WorkflowAppLogApi.get)(WorkflowAppLogApi(), _context())

    assert response == {"page": 2, "limit": 5, "total": 0, "has_more": False, "data": []}
    call = workflows.list_logs.call_args
    assert call.args == (_context(),)
    assert call.kwargs["status"] == "succeeded"
    assert call.kwargs["created_at_after"] == datetime(2026, 1, 1, tzinfo=UTC)
