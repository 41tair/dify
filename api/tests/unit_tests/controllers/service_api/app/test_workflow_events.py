from inspect import unwrap
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import NotFound

from controllers.service_api.app.workflow_events import WorkflowEventsApi
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
        "controllers.service_api.app.workflow_events.application_services",
        return_value=SimpleNamespace(service_api_workflows=workflows),
    )


def test_stream_events_keeps_sse_serialization_in_controller(flask_app: Flask) -> None:
    workflows = MagicMock()
    workflows.stream_events.return_value = iter(["data: one\n\n", "data: two\n\n"])

    with (
        flask_app.test_request_context(
            "/?user=external-1&include_state_snapshot=true&continue_on_pause=true"
        ),
        _install(workflows),
    ):
        response = unwrap(WorkflowEventsApi.get)(WorkflowEventsApi(), _context(), "run-1")
        body = response.get_data(as_text=True)

    assert body == "data: one\n\ndata: two\n\n"
    assert response.mimetype == "text/event-stream"
    assert response.headers["Cache-Control"] == "no-cache"
    workflows.stream_events.assert_called_once_with(
        _context(),
        task_id="run-1",
        include_state_snapshot=True,
        continue_on_pause=True,
    )


def test_stream_events_maps_missing_run(flask_app: Flask) -> None:
    workflows = MagicMock()
    workflows.stream_events.side_effect = ServiceApiWorkflowRunNotFoundError()

    with (
        flask_app.test_request_context("/?user=external-1"),
        _install(workflows),
        pytest.raises(NotFound, match="Workflow run not found"),
    ):
        unwrap(WorkflowEventsApi.get)(WorkflowEventsApi(), _context(), "missing")
