"""
Service API workflow resume event stream endpoints.
"""

from flask import Response, request
from flask_restx import Resource
from pydantic import BaseModel, Field
from werkzeug.exceptions import NotFound

from controllers.common.fields import EventStreamResponse
from controllers.common.schema import query_params_from_model, register_response_schema_model, register_schema_models
from controllers.service_api import service_api_ns
from controllers.service_api.app.error import NotWorkflowAppError
from controllers.service_api.flask_admission import service_api_admission
from controllers.service_api.schema import event_stream_response
from extensions.ext_application_services import application_services
from machinery.context import ServiceApiRequestContext
from services.entities.service_api_entities import ServiceApiEndUserRequirement, ServiceApiEndUserSource
from services.service_api_workflow_service import (
    ServiceApiNotWorkflowAppError,
    ServiceApiWorkflowRunNotFoundError,
)


class WorkflowEventsQuery(BaseModel):
    user: str = Field(
        ...,
        description="End-user identifier that originally triggered the run. Must match the creator of the run.",
    )
    include_state_snapshot: bool = Field(
        default=False,
        description=(
            "When `true`, replay from the persisted state snapshot to include a status summary of already-executed "
            "nodes before streaming new events."
        ),
    )
    continue_on_pause: bool = Field(
        default=False,
        description=(
            "Set to `true` to keep the stream open across multiple `workflow_paused` events, which is useful when "
            "the workflow has more than one Human Input node in sequence. By default, the stream closes after the "
            "first pause."
        ),
    )


register_schema_models(service_api_ns, WorkflowEventsQuery)
register_response_schema_model(service_api_ns, EventStreamResponse)


@service_api_ns.route("/workflow/<string:task_id>/events")
class WorkflowEventsApi(Resource):
    """Service API for getting workflow execution events after resume."""

    @service_api_ns.doc(
        summary="Stream Workflow Events",
        description=(
            "Resume the Server-Sent Events stream for a workflow run after a pause or a dropped SSE "
            "connection. For runs that have already finished, the stream emits a single "
            "`workflow_finished` event and closes."
        ),
        tags=["Chatflows", "Workflows"],
        responses={
            200: (
                "Server-Sent Events stream. Each event is delivered as `data: {JSON}\\n\\n`. Event payloads "
                "follow the same schemas as the original streaming response."
            ),
            400: "`not_workflow_app` : Please check if your app mode matches the right API route.",
            404: "`not_found` : Workflow run not found.",
        },
    )
    @event_stream_response(service_api_ns)
    @service_api_ns.doc("get_workflow_events")
    @service_api_ns.doc(description="Get workflow execution events stream after resume")
    @service_api_ns.doc(params={"task_id": "Workflow run ID returned by the original workflow run request."})
    @service_api_ns.doc(params=query_params_from_model(WorkflowEventsQuery))
    @service_api_ns.doc(
        responses={
            200: "SSE event stream",
            401: "Unauthorized - invalid API token",
            404: "Workflow run not found",
        }
    )
    @service_api_ns.response(200, "SSE event stream", service_api_ns.models[EventStreamResponse.__name__])
    @service_api_admission(
        end_user=ServiceApiEndUserRequirement(source=ServiceApiEndUserSource.QUERY, required=True)
    )
    def get(self, request_context: ServiceApiRequestContext, task_id: str):
        query = WorkflowEventsQuery.model_validate(request.args.to_dict())
        try:
            events = application_services().service_api_workflows.stream_events(
                request_context,
                task_id=task_id,
                include_state_snapshot=query.include_state_snapshot,
                continue_on_pause=query.continue_on_pause,
            )
        except ServiceApiNotWorkflowAppError as error:
            raise NotWorkflowAppError() from error
        except ServiceApiWorkflowRunNotFoundError as error:
            raise NotFound("Workflow run not found") from error

        return Response(
            events,
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )
