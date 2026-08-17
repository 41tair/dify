import logging
from typing import Literal

from dateutil.parser import isoparse
from flask import request
from flask_restx import Resource
from pydantic import BaseModel, Field
from pydantic.json_schema import SkipJsonSchema
from werkzeug.exceptions import BadRequest, InternalServerError, NotFound

from controllers.common.controller_schemas import WorkflowRunPayload as WorkflowRunPayloadBase
from controllers.common.fields import GeneratedAppResponse, SimpleResultResponse
from controllers.common.schema import (
    query_params_from_model,
    query_params_from_request,
    register_response_schema_models,
    register_schema_models,
)
from controllers.service_api import service_api_ns
from controllers.service_api.app.error import (
    CompletionRequestError,
    NotWorkflowAppError,
    ProviderModelCurrentlyNotSupportError,
    ProviderNotInitializeError,
    ProviderQuotaExceededError,
    WorkflowVersionExecutionNotAllowedError,
)
from controllers.service_api.flask_admission import service_api_admission
from controllers.service_api.schema import (
    expect_user_json,
    expect_with_user,
    json_or_event_stream_response,
)
from controllers.web.error import InvokeRateLimitError as InvokeRateLimitHttpError
from core.errors.error import (
    ModelCurrentlyNotSupportError,
    ProviderTokenNotInitError,
    QuotaExceededError,
)
from core.helper.trace_id_helper import get_external_trace_id, get_trace_session_id, omit_trace_session_id_from_payload
from extensions.ext_application_services import application_services
from fields.service_api_workflow_fields import (
    WorkflowAppLogPaginationResponse,
    WorkflowAppLogPartialResponse,
    WorkflowRunForLogResponse,
    WorkflowRunResponse,
)
from graphon.model_runtime.errors.invoke import InvokeError
from libs import helper
from machinery.context import ServiceApiRequestContext
from services.entities.service_api_entities import ServiceApiEndUserRequirement, ServiceApiEndUserSource
from services.errors.app import IsDraftWorkflowError, WorkflowIdFormatError, WorkflowNotFoundError
from services.errors.llm import InvokeRateLimitError
from services.service_api_workflow_service import (
    ServiceApiNotWorkflowAppError,
    ServiceApiWorkflowRunNotFoundError,
    ServiceApiWorkflowVersionNotAllowedError,
)

logger = logging.getLogger(__name__)


class WorkflowRunPayload(WorkflowRunPayloadBase):
    response_mode: Literal["blocking", "streaming"] | None = Field(
        default=None,
        description=(
            "Response mode. Use `blocking` for synchronous responses or `streaming` for Server-Sent Events. "
            "When omitted, the request runs in blocking mode."
        ),
    )
    trace_session_id: SkipJsonSchema[str | None] = Field(
        default=None, description="Trace session ID for observability grouping"
    )


class WorkflowLogQuery(BaseModel):
    keyword: str | None = Field(default=None, description="Keyword to search in logs.")
    status: Literal["succeeded", "failed", "stopped"] | None = Field(
        default=None,
        description="Filter by execution status.",
    )
    created_at__before: str | None = Field(
        default=None,
        description="Filter logs created before this ISO 8601 timestamp.",
        json_schema_extra={"format": "date-time"},
    )
    created_at__after: str | None = Field(
        default=None,
        description="Filter logs created after this ISO 8601 timestamp.",
        json_schema_extra={"format": "date-time"},
    )
    created_by_end_user_session_id: str | None = Field(
        default=None,
        description="Filter by end user session ID.",
    )
    created_by_account: str | None = Field(default=None, description="Filter by account ID.")
    page: int = Field(default=1, ge=1, le=99999, description="Page number for pagination.")
    limit: int = Field(default=20, ge=1, le=100, description="Number of items per page.")


register_schema_models(service_api_ns, WorkflowRunPayload, WorkflowLogQuery)
register_response_schema_models(service_api_ns, GeneratedAppResponse, SimpleResultResponse)


register_response_schema_models(
    service_api_ns,
    WorkflowRunResponse,
    WorkflowRunForLogResponse,
    WorkflowAppLogPartialResponse,
    WorkflowAppLogPaginationResponse,
)


@service_api_ns.route("/workflows/run/<string:workflow_run_id>")
class WorkflowRunDetailApi(Resource):
    @service_api_ns.doc(
        summary="Get Workflow Run Detail",
        description="Retrieve the current execution results of a workflow task based on the workflow execution ID.",
        tags=["Chatflows", "Workflows"],
        responses={
            200: "Successfully retrieved workflow run details.",
            400: "`not_workflow_app` : App mode does not match the API route.",
            404: "`not_found` : Workflow run not found.",
        },
    )
    @service_api_ns.doc("get_workflow_run_detail")
    @service_api_ns.doc(description="Get workflow run details")
    @service_api_ns.doc(
        params={
            "workflow_run_id": "Workflow run ID, obtained from the workflow execution response or streaming events."
        }
    )
    @service_api_ns.doc(
        responses={
            200: "Workflow run details retrieved successfully",
            401: "Unauthorized - invalid API token",
            404: "Workflow run not found",
        }
    )
    @service_api_admission()
    @service_api_ns.response(
        200,
        "Workflow run details retrieved successfully",
        service_api_ns.models[WorkflowRunResponse.__name__],
    )
    def get(self, request_context: ServiceApiRequestContext, workflow_run_id: str):
        """Get a workflow task running detail.

        Returns detailed information about a specific workflow run.
        """
        try:
            result = application_services().service_api_workflows.get_run(
                request_context,
                workflow_run_id=workflow_run_id,
            )
        except ServiceApiNotWorkflowAppError as error:
            raise NotWorkflowAppError() from error
        except ServiceApiWorkflowRunNotFoundError as error:
            raise NotFound("Workflow run not found.") from error
        return WorkflowRunResponse.model_validate(result).model_dump(mode="json")


@service_api_ns.route("/workflows/run")
class WorkflowRunApi(Resource):
    @service_api_ns.doc(
        summary="Run Workflow",
        description="Execute a workflow. Cannot be executed without a published workflow.",
        tags=["Workflows"],
        responses={
            200: (
                "Successful response. The content type and structure depend on the `response_mode` parameter "
                "in the request.\n"
                "\n"
                "- If `response_mode` is `blocking`, returns `application/json` with a "
                "`WorkflowBlockingResponse` object.\n"
                "- If `response_mode` is `streaming`, returns `text/event-stream` with a stream of "
                "`ChunkWorkflowEvent` objects."
            ),
            400: (
                "- `not_workflow_app` : App mode does not match the API route.\n"
                "- `provider_not_initialize` : No valid model provider credentials found.\n"
                "- `provider_quota_exceeded` : Model provider quota exhausted.\n"
                "- `model_currently_not_support` : Current model unavailable.\n"
                "- `completion_request_error` : Workflow execution request failed.\n"
                "- `invalid_param` : Invalid parameter value."
            ),
            429: (
                "- `too_many_requests` : Too many concurrent requests for this app.\n"
                "- `rate_limit_error` : The upstream model provider rate limit was exceeded."
            ),
            500: "`internal_server_error` : Internal server error.",
        },
    )
    @expect_with_user(service_api_ns, WorkflowRunPayload)
    @json_or_event_stream_response(service_api_ns)
    @service_api_ns.doc("run_workflow")
    @service_api_ns.doc(description="Execute a workflow")
    @service_api_ns.doc(
        responses={
            200: "Workflow executed successfully",
            400: "Bad request - invalid parameters or workflow issues",
            401: "Unauthorized - invalid API token",
            404: "Workflow not found",
            429: "Rate limit exceeded",
            500: "Internal server error",
        }
    )
    @service_api_ns.response(
        200,
        "Workflow executed successfully",
        service_api_ns.models[GeneratedAppResponse.__name__],
    )
    @service_api_admission(
        end_user=ServiceApiEndUserRequirement(source=ServiceApiEndUserSource.JSON, required=True)
    )
    def post(self, request_context: ServiceApiRequestContext):
        """Execute a workflow.

        Runs a workflow with the provided inputs and returns the results.
        Supports both blocking and streaming response modes.
        """
        payload = WorkflowRunPayload.model_validate(omit_trace_session_id_from_payload(service_api_ns.payload) or {})
        args = payload.model_dump(exclude_none=True)
        trace_session_id = get_trace_session_id(request)
        if trace_session_id:
            args["trace_session_id"] = trace_session_id
        external_trace_id = get_external_trace_id(request)
        if external_trace_id:
            args["external_trace_id"] = external_trace_id
        streaming = payload.response_mode == "streaming"

        try:
            response = application_services().service_api_workflows.run(
                request_context,
                args=args,
                streaming=streaming,
                workflow_id=None,
            )

            # response-contract:ignore compact_generate_response
            return helper.compact_generate_response(response)
        except ServiceApiNotWorkflowAppError as error:
            raise NotWorkflowAppError() from error
        except ProviderTokenNotInitError as ex:
            raise ProviderNotInitializeError(ex.description)
        except QuotaExceededError:
            raise ProviderQuotaExceededError()
        except ModelCurrentlyNotSupportError:
            raise ProviderModelCurrentlyNotSupportError()
        except InvokeRateLimitError as ex:
            raise InvokeRateLimitHttpError(ex.description)
        except InvokeError as e:
            raise CompletionRequestError(e.description)
        except ValueError as e:
            raise e
        except Exception:
            logger.exception("internal server error.")
            raise InternalServerError()


@service_api_ns.route("/workflows/<string:workflow_id>/run")
class WorkflowRunByIdApi(Resource):
    @service_api_ns.doc(
        summary="Run Workflow by ID",
        description=(
            "Execute a specific workflow version identified by its ID. Useful for running a particular "
            "published version of the workflow."
        ),
        tags=["Workflows"],
        responses={
            200: (
                "Successful response. The content type and structure depend on the `response_mode` parameter "
                "in the request.\n"
                "\n"
                "- If `response_mode` is `blocking`, returns `application/json` with a "
                "`WorkflowBlockingResponse` object.\n"
                "- If `response_mode` is `streaming`, returns `text/event-stream` with a stream of "
                "`ChunkWorkflowEvent` objects."
            ),
            400: (
                "- `not_workflow_app` : App mode does not match the API route.\n"
                "- `bad_request` : Workflow is a draft or has an invalid ID format.\n"
                "- `provider_not_initialize` : No valid model provider credentials found.\n"
                "- `provider_quota_exceeded` : Model provider quota exhausted.\n"
                "- `model_currently_not_support` : Current model unavailable.\n"
                "- `completion_request_error` : Workflow execution request failed.\n"
                "- `invalid_param` : Required parameter missing or invalid."
            ),
            403: (
                "`workflow_version_execution_not_allowed` : Workflow version execution is unavailable on the "
                "current plan. Upgrade to a paid plan."
            ),
            404: "`not_found` : Workflow not found.",
            429: (
                "- `too_many_requests` : Too many concurrent requests for this app.\n"
                "- `rate_limit_error` : The upstream model provider rate limit was exceeded."
            ),
            500: "`internal_server_error` : Internal server error.",
        },
    )
    @expect_with_user(service_api_ns, WorkflowRunPayload)
    @json_or_event_stream_response(service_api_ns)
    @service_api_ns.doc("run_workflow_by_id")
    @service_api_ns.doc(description="Execute a specific workflow by ID")
    @service_api_ns.doc(
        params={
            "workflow_id": (
                "Workflow ID of the specific version to execute. This value is returned in the `workflow_id` field "
                "of workflow run responses."
            )
        }
    )
    @service_api_ns.doc(
        responses={
            200: "Workflow executed successfully",
            400: "Bad request - invalid parameters or workflow issues",
            401: "Unauthorized - invalid API token",
            403: "Forbidden - upgrade to a paid plan to execute a specific workflow version",
            404: "Workflow not found",
            429: "Rate limit exceeded",
            500: "Internal server error",
        }
    )
    @service_api_ns.response(
        200,
        "Workflow executed successfully",
        service_api_ns.models[GeneratedAppResponse.__name__],
    )
    @service_api_admission(
        end_user=ServiceApiEndUserRequirement(source=ServiceApiEndUserSource.JSON, required=True)
    )
    def post(self, request_context: ServiceApiRequestContext, workflow_id: str):
        """Run specific workflow by ID.

        Executes a specific workflow version identified by its ID.
        """
        payload = WorkflowRunPayload.model_validate(omit_trace_session_id_from_payload(service_api_ns.payload) or {})
        args = payload.model_dump(exclude_none=True)
        trace_session_id = get_trace_session_id(request)
        if trace_session_id:
            args["trace_session_id"] = trace_session_id

        # Add workflow_id to args for AppGenerateService
        args["workflow_id"] = workflow_id

        external_trace_id = get_external_trace_id(request)
        if external_trace_id:
            args["external_trace_id"] = external_trace_id
        streaming = payload.response_mode == "streaming"

        try:
            response = application_services().service_api_workflows.run(
                request_context,
                args=args,
                streaming=streaming,
                workflow_id=workflow_id,
            )

            # response-contract:ignore compact_generate_response
            return helper.compact_generate_response(response)
        except ServiceApiNotWorkflowAppError as error:
            raise NotWorkflowAppError() from error
        except ServiceApiWorkflowVersionNotAllowedError as error:
            raise WorkflowVersionExecutionNotAllowedError() from error
        except WorkflowNotFoundError as ex:
            raise NotFound(str(ex))
        except IsDraftWorkflowError as ex:
            raise BadRequest(str(ex))
        except WorkflowIdFormatError as ex:
            raise BadRequest(str(ex))
        except ProviderTokenNotInitError as ex:
            raise ProviderNotInitializeError(ex.description)
        except QuotaExceededError:
            raise ProviderQuotaExceededError()
        except ModelCurrentlyNotSupportError:
            raise ProviderModelCurrentlyNotSupportError()
        except InvokeRateLimitError as ex:
            raise InvokeRateLimitHttpError(ex.description)
        except InvokeError as e:
            raise CompletionRequestError(e.description)
        except ValueError as e:
            raise e
        except Exception:
            logger.exception("internal server error.")
            raise InternalServerError()


@service_api_ns.route("/workflows/tasks/<string:task_id>/stop")
class WorkflowTaskStopApi(Resource):
    @service_api_ns.doc(
        summary="Stop Workflow Task",
        description="Stop a running workflow task. Only supported in `streaming` mode.",
        tags=["Workflows"],
        responses={
            400: (
                "- `not_workflow_app` : App mode does not match the API route.\n"
                "- `invalid_param` : Required parameter missing or invalid."
            ),
        },
    )
    @expect_user_json(service_api_ns)
    @service_api_ns.doc("stop_workflow_task")
    @service_api_ns.doc(description="Stop a running workflow task")
    @service_api_ns.doc(
        params={"task_id": "Task ID, obtained from the streaming chunk returned by the Run Workflow API."}
    )
    @service_api_ns.doc(
        responses={
            200: "Task stopped successfully",
            401: "Unauthorized - invalid API token",
            404: "Task not found",
        }
    )
    @service_api_ns.response(200, "Task stopped successfully", service_api_ns.models[SimpleResultResponse.__name__])
    @service_api_admission(
        end_user=ServiceApiEndUserRequirement(source=ServiceApiEndUserSource.JSON, required=True)
    )
    def post(self, request_context: ServiceApiRequestContext, task_id: str):
        """Stop a running workflow task."""
        try:
            application_services().service_api_workflows.stop(request_context, task_id=task_id)
        except ServiceApiNotWorkflowAppError as error:
            raise NotWorkflowAppError() from error

        return SimpleResultResponse(result="success").model_dump()


@service_api_ns.route("/workflows/logs")
class WorkflowAppLogApi(Resource):
    @service_api_ns.doc(
        summary="List Workflow Logs",
        description="Retrieve paginated workflow execution logs with filtering options.",
        tags=["Chatflows", "Workflows"],
        responses={
            200: "Successfully retrieved workflow logs.",
        },
    )
    @service_api_ns.doc(params=query_params_from_model(WorkflowLogQuery))
    @service_api_ns.doc("get_workflow_logs")
    @service_api_ns.doc(description="Get workflow execution logs")
    @service_api_ns.doc(
        responses={
            200: "Logs retrieved successfully",
            401: "Unauthorized - invalid API token",
        }
    )
    @service_api_admission()
    @service_api_ns.response(
        200,
        "Logs retrieved successfully",
        service_api_ns.models[WorkflowAppLogPaginationResponse.__name__],
    )
    def get(self, request_context: ServiceApiRequestContext):
        """Get workflow app logs.

        Returns paginated workflow execution logs with filtering options.
        """
        args = query_params_from_request(WorkflowLogQuery)

        created_at_before = isoparse(args.created_at__before) if args.created_at__before else None
        created_at_after = isoparse(args.created_at__after) if args.created_at__after else None

        try:
            workflow_app_log_pagination = application_services().service_api_workflows.list_logs(
                request_context,
                keyword=args.keyword,
                status=args.status,
                created_at_before=created_at_before,
                created_at_after=created_at_after,
                page=args.page,
                limit=args.limit,
                created_by_end_user_session_id=args.created_by_end_user_session_id,
                created_by_account=args.created_by_account,
            )
        except ServiceApiNotWorkflowAppError as error:
            raise NotWorkflowAppError() from error
        return WorkflowAppLogPaginationResponse.model_validate(workflow_app_log_pagination).model_dump(mode="json")
