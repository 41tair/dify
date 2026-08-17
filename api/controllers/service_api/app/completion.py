import logging
from typing import Any, Literal
from uuid import UUID

from flask import request
from flask_restx import Resource
from pydantic import BaseModel, Field, field_validator
from pydantic.json_schema import SkipJsonSchema
from werkzeug.exceptions import BadRequest, InternalServerError, NotFound

import services
from controllers.common.fields import SimpleResultResponse
from controllers.common.schema import register_response_schema_models, register_schema_models
from controllers.service_api import service_api_ns
from controllers.service_api.app.error import (
    AgentNotPublishedError,
    AppUnavailableError,
    CompletionRequestError,
    ConversationCompletedError,
    NotChatAppError,
    ProviderModelCurrentlyNotSupportError,
    ProviderNotInitializeError,
    ProviderQuotaExceededError,
    WorkflowVersionExecutionNotAllowedError,
)
from controllers.service_api.flask_admission import service_api_admission
from controllers.service_api.schema import (
    InputFileList,
    expect_user_json,
    expect_with_user,
    json_or_event_stream_response,
)
from controllers.web.error import InvokeRateLimitError as InvokeRateLimitHttpError
from core.app.apps.agent_app.errors import AgentAppNotPublishedError
from core.errors.error import (
    ModelCurrentlyNotSupportError,
    ProviderTokenNotInitError,
    QuotaExceededError,
)
from core.helper.trace_id_helper import get_external_trace_id, get_trace_session_id, omit_trace_session_id_from_payload
from extensions.ext_application_services import application_services
from graphon.model_runtime.errors.invoke import InvokeError
from libs import helper
from libs.helper import UUIDStrOrEmpty
from machinery.context import ServiceApiRequestContext
from services.entities.service_api_entities import ServiceApiEndUserRequirement, ServiceApiEndUserSource
from services.errors.app import IsDraftWorkflowError, WorkflowIdFormatError, WorkflowNotFoundError
from services.errors.llm import InvokeRateLimitError
from services.service_api_generation_service import (
    ServiceApiAgentStreamingOnlyError,
    ServiceApiGenerationAppUnavailableError,
    ServiceApiGenerationNotChatAppError,
    ServiceApiWorkflowVersionNotAllowedError,
)

logger = logging.getLogger(__name__)


class CompletionRequestPayload(BaseModel):
    inputs: dict[str, Any] = Field(
        description=(
            "Values for app-defined variables. Refer to the `user_input_form` field in the "
            "[Get App Parameters](/api-reference/applications/get-app-parameters) response to discover expected "
            "variable names and types."
        )
    )
    query: str = Field(default="", description="User input or prompt content.")
    files: InputFileList = Field(
        default=None,
        description=(
            "File list for multimodal understanding, including images, documents, audio, and video. To attach a "
            "local file, first upload it via [Upload File](/api-reference/files/upload-file) and use the returned "
            "`id` as `upload_file_id` with `transfer_method: local_file`."
        ),
    )
    response_mode: Literal["blocking", "streaming"] | None = Field(
        default=None,
        description=(
            "Response mode. `streaming` uses Server-Sent Events; `blocking` returns after completion. When omitted, "
            "the request runs in blocking mode."
        ),
    )
    retriever_from: SkipJsonSchema[str] = Field(default="dev")
    trace_session_id: SkipJsonSchema[str | None] = Field(
        default=None, description="Trace session ID for observability grouping"
    )


class ChatRequestPayload(BaseModel):
    inputs: dict[str, Any] = Field(
        description=(
            "Values for app-defined variables. Refer to the `user_input_form` field in the "
            "[Get App Parameters](/api-reference/applications/get-app-parameters) response to discover expected "
            "variable names and types."
        )
    )
    query: str = Field(description="User input or question content.")
    files: InputFileList = Field(
        default=None,
        description=(
            "File list for multimodal understanding, including images, documents, audio, and video. To attach a "
            "local file, first upload it via [Upload File](/api-reference/files/upload-file) and use the returned "
            "`id` as `upload_file_id` with `transfer_method: local_file`."
        ),
    )
    response_mode: Literal["blocking", "streaming"] | None = Field(
        default=None,
        description=(
            "Response mode. `streaming` uses Server-Sent Events; `blocking` returns after completion. New Agent app "
            "mode supports streaming only. When omitted, non-Agent apps run in blocking mode and new Agent apps stream."
        ),
    )
    conversation_id: UUIDStrOrEmpty | None = Field(
        default=None,
        description=(
            "Conversation ID to continue a conversation. Omit this field or pass an empty string to start a new "
            "conversation, then pass the returned `conversation_id` in subsequent requests."
        ),
    )
    retriever_from: SkipJsonSchema[str] = Field(default="dev")
    auto_generate_name: bool = Field(
        default=True,
        description=(
            "Auto-generate the conversation title. If `false`, use the Rename Conversation API with "
            "`auto_generate: true` to generate the title asynchronously."
        ),
    )
    workflow_id: str | None = Field(
        default=None,
        description=(
            "Published workflow version ID to execute for advanced chat. If omitted, the app's current published "
            "workflow is used."
        ),
    )
    trace_session_id: SkipJsonSchema[str | None] = Field(
        default=None, description="Trace session ID for observability grouping"
    )

    @field_validator("conversation_id", mode="before")
    @classmethod
    def normalize_conversation_id(cls, value: str | UUID | None) -> str | None:
        """Allow missing or blank conversation IDs; enforce UUID format when provided."""
        if isinstance(value, str):
            value = value.strip()

        if not value:
            return None

        try:
            return helper.uuid_value(value)
        except ValueError as exc:
            raise ValueError("conversation_id must be a valid UUID") from exc


register_schema_models(service_api_ns, CompletionRequestPayload, ChatRequestPayload)
register_response_schema_models(service_api_ns, SimpleResultResponse)


@service_api_ns.route("/completion-messages")
class CompletionApi(Resource):
    @service_api_ns.doc(
        summary="Send Completion Message",
        description="Send a request to the text generation application.",
        tags=["Completions"],
        responses={
            200: (
                "Successful response. The content type and structure depend on the `response_mode` parameter "
                "in the request.\n"
                "\n"
                "- If `response_mode` is `blocking`, returns `application/json` with a `CompletionResponse` "
                "object.\n"
                "- If `response_mode` is `streaming`, returns `text/event-stream` with a stream of "
                "`ChunkCompletionEvent` objects."
            ),
            400: (
                "- `app_unavailable` : App unavailable or misconfigured.\n"
                "- `provider_not_initialize` : No valid model provider credentials found.\n"
                "- `provider_quota_exceeded` : Model provider quota exhausted.\n"
                "- `model_currently_not_support` : Current model unavailable.\n"
                "- `completion_request_error` : Text generation failed."
            ),
            429: "`too_many_requests` : Too many concurrent requests for this app.",
            500: "`internal_server_error` : Internal server error.",
        },
    )
    @expect_with_user(service_api_ns, CompletionRequestPayload)
    @json_or_event_stream_response(service_api_ns)
    @service_api_ns.doc("create_completion")
    @service_api_ns.doc(description="Create a completion for the given prompt")
    @service_api_ns.doc(
        responses={
            200: "Completion created successfully",
            400: "Bad request - invalid parameters",
            401: "Unauthorized - invalid API token",
            404: "Conversation not found",
            500: "Internal server error",
        }
    )
    @service_api_ns.response(200, "Completion created successfully")
    @service_api_admission(
        end_user=ServiceApiEndUserRequirement(source=ServiceApiEndUserSource.JSON, required=True)
    )
    def post(self, request_context: ServiceApiRequestContext):
        """Create a completion for the given prompt.

        This endpoint generates a completion based on the provided inputs and query.
        Supports both blocking and streaming response modes.
        """
        payload = CompletionRequestPayload.model_validate(
            omit_trace_session_id_from_payload(service_api_ns.payload) or {}
        )
        external_trace_id = get_external_trace_id(request)
        args = payload.model_dump(exclude_none=True)
        trace_session_id = get_trace_session_id(request)
        if trace_session_id:
            args["trace_session_id"] = trace_session_id
        if external_trace_id:
            args["external_trace_id"] = external_trace_id

        streaming = payload.response_mode == "streaming"

        args["auto_generate_name"] = False

        try:
            response = application_services().service_api_generation.generate_completion(
                request_context,
                args=args,
                streaming=streaming,
            )

            # response-contract:ignore compact_generate_response
            return helper.compact_generate_response(response)
        except ServiceApiGenerationAppUnavailableError as error:
            raise AppUnavailableError() from error
        except services.errors.conversation.ConversationNotExistsError:
            raise NotFound("Conversation Not Exists.")
        except services.errors.conversation.ConversationCompletedError:
            raise ConversationCompletedError()
        except services.errors.app_model_config.AppModelConfigBrokenError:
            logger.exception("App model config broken.")
            raise AppUnavailableError()
        except AgentAppNotPublishedError:
            raise AgentNotPublishedError()
        except ProviderTokenNotInitError as ex:
            raise ProviderNotInitializeError(ex.description)
        except QuotaExceededError:
            raise ProviderQuotaExceededError()
        except ModelCurrentlyNotSupportError:
            raise ProviderModelCurrentlyNotSupportError()
        except InvokeError as e:
            raise CompletionRequestError(e.description)
        except ValueError as e:
            raise e
        except Exception:
            logger.exception("internal server error.")
            raise InternalServerError()


@service_api_ns.route("/completion-messages/<string:task_id>/stop")
class CompletionStopApi(Resource):
    @service_api_ns.doc(
        summary="Stop Completion Message Generation",
        description="Stops a completion message generation task. Only supported in `streaming` mode.",
        tags=["Completions"],
        responses={
            400: "`app_unavailable` : App unavailable or misconfigured.",
        },
    )
    @expect_user_json(service_api_ns)
    @service_api_ns.doc("stop_completion")
    @service_api_ns.doc(description="Stop a running completion task")
    @service_api_ns.doc(
        params={"task_id": ("Task ID, obtained from a streaming chunk returned by the Send Completion Message API.")}
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
        """Stop a running completion task."""
        try:
            application_services().service_api_generation.stop_completion(request_context, task_id=task_id)
        except ServiceApiGenerationAppUnavailableError as error:
            raise AppUnavailableError() from error

        return SimpleResultResponse(result="success").model_dump(mode="json"), 200


@service_api_ns.route("/chat-messages")
class ChatApi(Resource):
    @service_api_ns.doc(
        summary="Send Chat Message",
        description="Send a request to the chat application.",
        tags=["Chats", "Chatflows"],
        responses={
            200: (
                "Successful response. The content type and structure depend on the `response_mode` parameter "
                "in the request.\n"
                "\n"
                "- If `response_mode` is `blocking`, returns `application/json` with a "
                "`ChatCompletionResponse` object.\n"
                "- If `response_mode` is `streaming`, returns `text/event-stream` with a stream of "
                "Server-Sent Events."
            ),
            400: (
                "- `app_unavailable` : App unavailable or misconfigured.\n"
                "- `not_chat_app` : App mode does not match the API route.\n"
                "- `conversation_completed` : The conversation has ended.\n"
                "- `provider_not_initialize` : No valid model provider credentials found.\n"
                "- `provider_quota_exceeded` : Model provider quota exhausted.\n"
                "- `model_currently_not_support` : Current model unavailable.\n"
                "- `completion_request_error` : Text generation failed."
            ),
            403: (
                "`workflow_version_execution_not_allowed` : Workflow version execution is unavailable on the "
                "current plan. Upgrade to a paid plan."
            ),
            404: "`not_found` : Conversation does not exist.",
            429: (
                "- `too_many_requests` : Too many concurrent requests for this app.\n"
                "- `rate_limit_error` : The upstream model provider rate limit was exceeded."
            ),
            500: "`internal_server_error` : Internal server error.",
        },
    )
    @expect_with_user(service_api_ns, ChatRequestPayload)
    @json_or_event_stream_response(service_api_ns)
    @service_api_ns.doc("create_chat_message")
    @service_api_ns.doc(description="Send a message in a chat conversation")
    @service_api_ns.doc(
        responses={
            200: "Message sent successfully",
            400: "Bad request - invalid parameters or workflow issues",
            401: "Unauthorized - invalid API token",
            403: "Forbidden - upgrade to a paid plan to execute a specific workflow version",
            404: "Conversation or workflow not found",
            429: "Rate limit exceeded",
            500: "Internal server error",
        }
    )
    @service_api_ns.response(200, "Message sent successfully")
    @service_api_admission(
        end_user=ServiceApiEndUserRequirement(source=ServiceApiEndUserSource.JSON, required=True)
    )
    def post(self, request_context: ServiceApiRequestContext):
        """Send a message in a chat conversation.

        This endpoint handles chat messages for chat, agent chat, and advanced chat applications.
        Supports conversation management and both blocking and streaming response modes.
        """
        payload = ChatRequestPayload.model_validate(omit_trace_session_id_from_payload(service_api_ns.payload) or {})

        external_trace_id = get_external_trace_id(request)
        args = payload.model_dump(exclude_none=True)
        trace_session_id = get_trace_session_id(request)
        if trace_session_id:
            args["trace_session_id"] = trace_session_id
        if external_trace_id:
            args["external_trace_id"] = external_trace_id

        try:
            response = application_services().service_api_generation.generate_chat(
                request_context,
                args=args,
                response_mode=payload.response_mode,
                workflow_id=payload.workflow_id,
                conversation_id=payload.conversation_id,
            )

            # response-contract:ignore compact_generate_response
            return helper.compact_generate_response(response)
        except ServiceApiGenerationNotChatAppError as error:
            raise NotChatAppError() from error
        except ServiceApiAgentStreamingOnlyError as error:
            raise BadRequest("Agent App only supports streaming response mode.") from error
        except ServiceApiWorkflowVersionNotAllowedError as error:
            raise WorkflowVersionExecutionNotAllowedError() from error
        except WorkflowNotFoundError as ex:
            raise NotFound(str(ex))
        except IsDraftWorkflowError as ex:
            raise BadRequest(str(ex))
        except WorkflowIdFormatError as ex:
            raise BadRequest(str(ex))
        except services.errors.conversation.ConversationNotExistsError:
            raise NotFound("Conversation Not Exists.")
        except services.errors.conversation.ConversationCompletedError:
            raise ConversationCompletedError()
        except services.errors.app_model_config.AppModelConfigBrokenError:
            logger.exception("App model config broken.")
            raise AppUnavailableError()
        except AgentAppNotPublishedError:
            raise AgentNotPublishedError()
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


@service_api_ns.route("/chat-messages/<string:task_id>/stop")
class ChatStopApi(Resource):
    @service_api_ns.doc(
        summary="Stop Chat Message Generation",
        description="Stops a chat message generation task. Only supported in `streaming` mode.",
        tags=["Chats", "Chatflows"],
        responses={
            400: "`not_chat_app` : App mode does not match the API route.",
        },
    )
    @expect_user_json(service_api_ns)
    @service_api_ns.doc("stop_chat_message")
    @service_api_ns.doc(description="Stop a running chat message generation")
    @service_api_ns.doc(
        params={"task_id": "Task ID, obtained from a streaming chunk returned by the Send Chat Message API."}
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
        """Stop a running chat message generation."""
        try:
            application_services().service_api_generation.stop_chat(request_context, task_id=task_id)
        except ServiceApiGenerationNotChatAppError as error:
            raise NotChatAppError() from error

        return SimpleResultResponse(result="success").model_dump(mode="json"), 200
