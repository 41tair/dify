"""
Service API human input form endpoints.

This module exposes app-token authenticated APIs for fetching and submitting
paused human input forms in workflow/chatflow runs.
"""

import json
import logging
from typing import Any

from flask import Response
from flask_restx import Resource
from pydantic import ConfigDict, Field
from werkzeug.exceptions import BadRequest, NotFound

from controllers.common.human_input import HumanInputFormSubmitPayload
from controllers.common.schema import register_response_schema_models, register_schema_models
from controllers.service_api import service_api_ns
from controllers.service_api.flask_admission import service_api_admission
from controllers.service_api.schema import expect_with_user
from extensions.ext_application_services import application_services
from fields.base import ResponseModel
from machinery.context import ServiceApiRequestContext
from services.entities.service_api_entities import ServiceApiEndUserRequirement, ServiceApiEndUserSource
from services.service_api_human_input_service import (
    ServiceApiHumanInputInvalidRecipientError,
    ServiceApiHumanInputNotFoundError,
)

logger = logging.getLogger(__name__)


class HumanInputFormDefinitionResponse(ResponseModel):
    form_content: str
    inputs: list[dict[str, Any]] = Field(default_factory=list)
    resolved_default_values: dict[str, str]
    user_actions: list[dict[str, Any]] = Field(default_factory=list)
    expiration_time: int | None = None


class HumanInputFormSubmitResponse(ResponseModel):
    model_config = ConfigDict(extra="forbid")


register_schema_models(service_api_ns, HumanInputFormSubmitPayload)
register_response_schema_models(service_api_ns, HumanInputFormDefinitionResponse, HumanInputFormSubmitResponse)


@service_api_ns.route("/form/human_input/<string:form_token>")
class WorkflowHumanInputFormApi(Resource):
    @service_api_ns.doc(
        summary="Get Human Input Form",
        description=(
            "Retrieve a paused Human Input form's contents using the `form_token` from a "
            "`human_input_required` event. Requires **WebApp** delivery."
        ),
        tags=["Human Input"],
        responses={
            200: "Form contents retrieved successfully.",
            404: "`not_found` : Form not found.",
            412: (
                "- `human_input_form_submitted` : Form already submitted. Forms are one-shot; the first "
                "response wins regardless of which user submits it.\n"
                "- `human_input_form_expired` : The form's expiration time passed before submission arrived."
            ),
        },
    )
    @service_api_ns.doc("get_human_input_form")
    @service_api_ns.doc(description="Get a paused human input form by token")
    @service_api_ns.doc(params={"form_token": "Human input form token"})
    @service_api_ns.doc(
        responses={
            200: "Form retrieved successfully",
            401: "Unauthorized - invalid API token",
            404: "Form not found",
            412: "Form already submitted or expired",
        }
    )
    @service_api_ns.response(
        200,
        "Form retrieved successfully",
        service_api_ns.models[HumanInputFormDefinitionResponse.__name__],
    )
    @service_api_admission()
    def get(self, request_context: ServiceApiRequestContext, form_token: str):
        try:
            payload = application_services().service_api_human_inputs.get_form(
                request_context,
                form_token=form_token,
            )
        except ServiceApiHumanInputNotFoundError as error:
            raise NotFound("Form not found") from error
        return Response(json.dumps(payload, ensure_ascii=False), mimetype="application/json")

    @service_api_ns.doc(
        summary="Submit Human Input Form",
        description=(
            "Submit the recipient's response to a paused Human Input form. The workflow resumes on "
            "acceptance; use [Stream Workflow Events](/api-reference/chatflows/stream-workflow-events) "
            "to follow subsequent events. Requires **WebApp** delivery."
        ),
        tags=["Human Input"],
        responses={
            200: "Form submitted successfully. The response body is an empty object.",
            400: (
                "- `bad_request` : Form recipient type is invalid.\n"
                "- `invalid_form_data` : Submission failed validation against the form definition."
            ),
            404: "`not_found` : Form not found.",
            412: (
                "- `human_input_form_submitted` : Form already submitted. Forms are one-shot; the first "
                "response wins regardless of which user submits it.\n"
                "- `human_input_form_expired` : The form's expiration time passed before submission arrived."
            ),
        },
    )
    @expect_with_user(service_api_ns, HumanInputFormSubmitPayload)
    @service_api_ns.doc("submit_human_input_form")
    @service_api_ns.doc(description="Submit a paused human input form by token")
    @service_api_ns.doc(params={"form_token": "Human input form token"})
    @service_api_ns.doc(
        responses={
            200: "Form submitted successfully",
            400: "Bad request - invalid submission data",
            401: "Unauthorized - invalid API token",
            404: "Form not found",
            412: "Form already submitted or expired",
        }
    )
    @service_api_ns.response(
        200,
        "Form submitted successfully",
        service_api_ns.models[HumanInputFormSubmitResponse.__name__],
    )
    @service_api_admission(
        end_user=ServiceApiEndUserRequirement(source=ServiceApiEndUserSource.JSON, required=True)
    )
    def post(self, request_context: ServiceApiRequestContext, form_token: str):
        payload = HumanInputFormSubmitPayload.model_validate(service_api_ns.payload or {})

        try:
            application_services().service_api_human_inputs.submit_form(
                request_context,
                form_token=form_token,
                action=payload.action,
                inputs=payload.inputs,
            )
        except ServiceApiHumanInputNotFoundError as error:
            raise NotFound("Form not found") from error
        except ServiceApiHumanInputInvalidRecipientError as error:
            logger.warning("Recipient type is None for form token=%s", form_token)
            raise BadRequest("Form recipient type is invalid") from error

        return {}, 200
