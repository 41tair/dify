import logging
from uuid import UUID

from flask import request
from flask_restx import Resource
from pydantic import BaseModel, Field
from werkzeug.exceptions import BadRequest, InternalServerError, NotFound

import services
from controllers.common.controller_schemas import MessageFeedbackPayload, MessageListQuery
from controllers.common.fields import SimpleResultStringListResponse
from controllers.common.schema import query_params_from_model, register_response_schema_models, register_schema_models
from controllers.service_api import service_api_ns
from controllers.service_api.app.error import NotChatAppError
from controllers.service_api.flask_admission import service_api_admission
from controllers.service_api.schema import expect_with_user
from extensions.ext_application_services import application_services
from fields.base import ResponseModel
from fields.conversation_fields import ResultResponse
from fields.message_fields import MessageInfiniteScrollPagination, MessageListItem
from machinery.context import ServiceApiRequestContext
from services.entities.service_api_entities import ServiceApiEndUserRequirement, ServiceApiEndUserSource
from services.errors.message import (
    FirstMessageNotExistsError,
    MessageNotExistsError,
    SuggestedQuestionsAfterAnswerDisabledError,
)
from services.service_api_conversation_service import ServiceApiNotChatAppError

logger = logging.getLogger(__name__)


class FeedbackListQuery(BaseModel):
    page: int = Field(default=1, ge=1, description="Page number for pagination.")
    limit: int = Field(default=20, ge=1, le=101, description="Number of records per page.")


class AppFeedbackResponse(ResponseModel):
    id: str
    app_id: str
    conversation_id: str
    message_id: str
    rating: str
    content: str | None = None
    from_source: str
    from_end_user_id: str | None = None
    from_account_id: str | None = None
    created_at: str
    updated_at: str


class AppFeedbackListResponse(ResponseModel):
    data: list[AppFeedbackResponse]


register_schema_models(service_api_ns, MessageListQuery, MessageFeedbackPayload, FeedbackListQuery)
register_response_schema_models(
    service_api_ns,
    ResultResponse,
    SimpleResultStringListResponse,
    MessageInfiniteScrollPagination,
    MessageListItem,
    AppFeedbackListResponse,
)


@service_api_ns.route("/messages")
class MessageListApi(Resource):
    @service_api_ns.doc("list_messages")
    @service_api_ns.doc(
        summary="List Conversation Messages",
        description=(
            "Returns historical chat records in a scrolling load format, with the first page returning "
            "the latest `limit` messages, i.e., in reverse order."
        ),
        tags=["Conversations"],
        responses={
            200: "Successfully retrieved conversation history.",
            400: "`not_chat_app` : App mode does not match the API route.",
            404: "- `not_found` : Conversation does not exist.\n- `not_found` : First message does not exist.",
        },
    )
    @service_api_ns.doc(params=query_params_from_model(MessageListQuery))
    @service_api_ns.doc(description="List messages in a conversation")
    @service_api_ns.doc(
        responses={
            200: "Messages retrieved successfully",
            400: "`not_chat_app` : App mode does not match the API route.",
            401: "Unauthorized - invalid API token",
            404: "Conversation or first message not found",
        }
    )
    @service_api_ns.response(
        200,
        "Messages retrieved successfully",
        service_api_ns.models[MessageInfiniteScrollPagination.__name__],
    )
    @service_api_admission(end_user=ServiceApiEndUserRequirement(source=ServiceApiEndUserSource.QUERY))
    def get(self, request_context: ServiceApiRequestContext):
        """List messages in a conversation.

        Retrieves messages with pagination support using first_id.
        """
        query_args = MessageListQuery.model_validate(request.args.to_dict())
        conversation_id = query_args.conversation_id
        first_id = query_args.first_id or None

        try:
            result = application_services().service_api_conversations.list_messages(
                request_context,
                conversation_id=conversation_id,
                first_id=first_id,
                limit=query_args.limit,
            )
            return MessageInfiniteScrollPagination.model_validate(result).model_dump(mode="json")
        except ServiceApiNotChatAppError as error:
            raise NotChatAppError() from error
        except services.errors.conversation.ConversationNotExistsError:
            raise NotFound("Conversation Not Exists.")
        except FirstMessageNotExistsError:
            raise NotFound("First Message Not Exists.")


@service_api_ns.route("/messages/<uuid:message_id>/feedbacks")
class MessageFeedbackApi(Resource):
    @expect_with_user(service_api_ns, MessageFeedbackPayload)
    @service_api_ns.response(200, "Feedback submitted successfully", service_api_ns.models[ResultResponse.__name__])
    @service_api_ns.doc("create_message_feedback")
    @service_api_ns.doc(
        summary="Submit Message Feedback",
        description=(
            "Submit feedback for a message. End users can rate messages as `like` or `dislike`, and "
            "optionally provide text feedback. Pass `null` for `rating` to revoke previously submitted feedback."
        ),
        tags=["Feedback"],
        responses={
            404: "`not_found` : Message does not exist.",
        },
    )
    @service_api_ns.doc(description="Submit feedback for a message")
    @service_api_ns.doc(params={"message_id": "Message ID."})
    @service_api_ns.doc(
        responses={
            200: "Feedback submitted successfully",
            401: "Unauthorized - invalid API token",
            404: "Message not found",
        }
    )
    @service_api_admission(
        end_user=ServiceApiEndUserRequirement(source=ServiceApiEndUserSource.JSON, required=True)
    )
    def post(self, request_context: ServiceApiRequestContext, message_id: UUID):
        """Submit feedback for a message.

        Allows users to rate messages as like/dislike and provide optional feedback content.
        """
        message_id_str = str(message_id)

        payload = MessageFeedbackPayload.model_validate(service_api_ns.payload or {})

        try:
            application_services().service_api_conversations.submit_feedback(
                request_context,
                message_id=message_id_str,
                rating=payload.rating,
                content=payload.content,
            )
        except ServiceApiNotChatAppError as error:
            raise NotChatAppError() from error
        except MessageNotExistsError:
            raise NotFound("Message Not Exists.")

        return ResultResponse(result="success").model_dump(mode="json")


@service_api_ns.route("/app/feedbacks")
class AppGetFeedbacksApi(Resource):
    @service_api_ns.doc("get_app_feedbacks")
    @service_api_ns.doc(
        summary="List App Feedbacks",
        description=(
            "Retrieve a paginated list of all feedback submitted for messages in this application, including both "
            "end-user and admin feedback."
        ),
        tags=["Feedback"],
        responses={
            200: "A list of application feedbacks.",
        },
    )
    @service_api_ns.doc(params=query_params_from_model(FeedbackListQuery))
    @service_api_ns.doc(description="Get all feedbacks for the application")
    @service_api_ns.doc(
        responses={
            200: "Feedbacks retrieved successfully",
            401: "Unauthorized - invalid API token",
        }
    )
    @service_api_ns.response(
        200,
        "Feedbacks retrieved successfully",
        service_api_ns.models[AppFeedbackListResponse.__name__],
    )
    @service_api_admission()
    def get(self, request_context: ServiceApiRequestContext):
        """Get all feedbacks for the application.

        Returns paginated list of all feedback submitted for messages in this app.
        """
        query_args = FeedbackListQuery.model_validate(request.args.to_dict())
        feedbacks = application_services().service_api_conversations.list_feedbacks(
            request_context,
            page=query_args.page,
            limit=query_args.limit,
        )
        return AppFeedbackListResponse.model_validate({"data": feedbacks}).model_dump(mode="json")


@service_api_ns.route("/messages/<uuid:message_id>/suggested")
class MessageSuggestedApi(Resource):
    @service_api_ns.doc("get_suggested_questions")
    @service_api_ns.doc(
        summary="Get Next Suggested Questions",
        description="Get next questions suggestions for the current message.",
        tags=["Chats", "Chatflows"],
        responses={
            200: "Successfully retrieved suggested questions.",
            400: (
                "- `not_chat_app` : App mode does not match the API route.\n"
                "- `bad_request` : Suggested questions feature is disabled."
            ),
            404: "`not_found` : Message does not exist.",
            500: "`internal_server_error` : Internal server error.",
        },
    )
    @service_api_ns.response(
        200,
        "Suggested questions retrieved successfully",
        service_api_ns.models[SimpleResultStringListResponse.__name__],
    )
    @service_api_ns.doc(description="Get suggested follow-up questions for a message")
    @service_api_ns.doc(params={"message_id": "Message ID"})
    @service_api_ns.doc(
        responses={
            200: "Suggested questions retrieved successfully",
            400: "Suggested questions feature is disabled",
            401: "Unauthorized - invalid API token",
            404: "Message not found",
            500: "Internal server error",
        }
    )
    @service_api_admission(
        end_user=ServiceApiEndUserRequirement(source=ServiceApiEndUserSource.QUERY, required=True)
    )
    def get(self, request_context: ServiceApiRequestContext, message_id: UUID):
        """Get suggested follow-up questions for a message.

        Returns AI-generated follow-up questions based on the message content.
        """
        message_id_str = str(message_id)
        try:
            questions = application_services().service_api_conversations.suggested_questions(
                request_context,
                message_id=message_id_str,
            )
        except ServiceApiNotChatAppError as error:
            raise NotChatAppError() from error
        except MessageNotExistsError:
            raise NotFound("Message Not Exists.")
        except SuggestedQuestionsAfterAnswerDisabledError:
            raise BadRequest("Suggested Questions Is Disabled.")
        except Exception:
            logger.exception("internal server error.")
            raise InternalServerError()

        return SimpleResultStringListResponse(result="success", data=questions).model_dump(mode="json")
