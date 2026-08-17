from typing import Literal
from uuid import UUID

from flask import request
from flask_restx import Resource
from flask_restx.api import HTTPStatus
from pydantic import BaseModel, Field, TypeAdapter
from werkzeug.exceptions import NotFound

from controllers.common.schema import query_params_from_model, register_response_schema_models, register_schema_models
from controllers.service_api import service_api_ns
from controllers.service_api.flask_admission import service_api_admission
from extensions.ext_application_services import application_services
from fields.annotation_fields import (
    Annotation,
    AnnotationJobStatusDetailResponse,
    AnnotationJobStatusResponse,
    AnnotationList,
)
from libs.helper import dump_response
from machinery.context import ServiceApiRequestContext
from services.service_api_annotation_service import ServiceApiAnnotationNotFoundError


class AnnotationCreatePayload(BaseModel):
    question: str = Field(description="Annotation question.")
    answer: str = Field(description="Annotation answer.")


class AnnotationReplyActionPayload(BaseModel):
    score_threshold: float = Field(
        description=(
            "Minimum similarity score for an annotation to be considered a match. Higher values require closer matches."
        ),
        json_schema_extra={"format": "float"},
    )
    embedding_provider_name: str = Field(description="Name of the embedding model provider.")
    embedding_model_name: str = Field(description="Name of the embedding model to use for annotation matching.")


class AnnotationListQuery(BaseModel):
    page: int = Field(default=1, ge=1, description="Page number for pagination.")
    limit: int = Field(default=20, ge=1, description="Number of items per page.")
    keyword: str = Field(default="", description="Keyword to filter annotations by question or answer content.")


ANNOTATION_REPLY_ACTION_PARAM = {
    "description": "Action to perform: `enable` or `disable`.",
    "enum": ["enable", "disable"],
    "type": "string",
}


register_schema_models(
    service_api_ns,
    AnnotationCreatePayload,
    AnnotationReplyActionPayload,
    AnnotationListQuery,
    Annotation,
    AnnotationList,
)
register_response_schema_models(
    service_api_ns,
    Annotation,
    AnnotationList,
    AnnotationJobStatusResponse,
    AnnotationJobStatusDetailResponse,
)


@service_api_ns.route("/apps/annotation-reply/<string:action>")
class AnnotationReplyActionApi(Resource):
    @service_api_ns.doc(
        summary="Configure Annotation Reply",
        description=(
            "Enables or disables the annotation reply feature. Requires embedding model configuration "
            "when enabling. Executes asynchronously — use [Get Annotation Reply Job "
            "Status](/api-reference/annotations/get-annotation-reply-job-status) to track progress."
        ),
        tags=["Annotations"],
        responses={
            200: "Annotation reply settings task initiated.",
        },
    )
    @service_api_ns.expect(service_api_ns.models[AnnotationReplyActionPayload.__name__])
    @service_api_ns.doc("annotation_reply_action")
    @service_api_ns.doc(description="Enable or disable annotation reply feature")
    @service_api_ns.doc(params={"action": ANNOTATION_REPLY_ACTION_PARAM})
    @service_api_ns.doc(
        responses={
            200: "Action completed successfully",
            401: "Unauthorized - invalid API token",
        }
    )
    @service_api_ns.response(
        200,
        "Action completed successfully",
        service_api_ns.models[AnnotationJobStatusResponse.__name__],
    )
    @service_api_admission()
    def post(self, request_context: ServiceApiRequestContext, action: Literal["enable", "disable"]):
        """Enable or disable annotation reply feature."""
        payload = AnnotationReplyActionPayload.model_validate(service_api_ns.payload or {})
        result = application_services().service_api_annotations.configure_reply(
            request_context,
            action=action,
            score_threshold=payload.score_threshold,
            embedding_provider_name=payload.embedding_provider_name,
            embedding_model_name=payload.embedding_model_name,
        )
        return dump_response(AnnotationJobStatusResponse, result), 200


@service_api_ns.route("/apps/annotation-reply/<string:action>/status/<uuid:job_id>")
class AnnotationReplyActionStatusApi(Resource):
    @service_api_ns.doc(
        summary="Get Annotation Reply Job Status",
        description=(
            "Retrieves the status of an asynchronous annotation reply configuration job started by "
            "[Configure Annotation Reply](/api-reference/annotations/configure-annotation-reply)."
        ),
        tags=["Annotations"],
        responses={
            200: "Successfully retrieved task status.",
            400: "`invalid_param` : The specified job does not exist.",
        },
    )
    @service_api_ns.doc("get_annotation_reply_action_status")
    @service_api_ns.doc(description="Get the status of an annotation reply action job")
    @service_api_ns.doc(
        params={
            "action": ANNOTATION_REPLY_ACTION_PARAM,
            "job_id": (
                "Job ID returned by "
                "[Configure Annotation Reply](/api-reference/annotations/configure-annotation-reply)."
            ),
        }
    )
    @service_api_ns.doc(
        responses={
            200: "Job status retrieved successfully",
            401: "Unauthorized - invalid API token",
            404: "Job not found",
        }
    )
    @service_api_ns.response(
        200,
        "Job status retrieved successfully",
        service_api_ns.models[AnnotationJobStatusDetailResponse.__name__],
    )
    @service_api_admission()
    def get(self, request_context: ServiceApiRequestContext, job_id: UUID, action: str):
        """Get the status of an annotation reply action job."""
        job_id_str = str(job_id)
        try:
            result = application_services().service_api_annotations.get_job(
                request_context,
                action=action,
                job_id=job_id_str,
            )
        except ServiceApiAnnotationNotFoundError as error:
            raise ValueError("The job does not exist.") from error
        return dump_response(AnnotationJobStatusDetailResponse, result), 200


@service_api_ns.route("/apps/annotations")
class AnnotationListApi(Resource):
    @service_api_ns.doc(
        summary="List Annotations",
        description="Retrieves a paginated list of annotations for the application. Supports keyword search filtering.",
        tags=["Annotations"],
        responses={
            200: "Successfully retrieved annotation list.",
        },
    )
    @service_api_ns.doc("list_annotations")
    @service_api_ns.doc(description="List annotations for the application")
    @service_api_ns.doc(params=query_params_from_model(AnnotationListQuery))
    @service_api_ns.doc(
        responses={
            200: "Annotations retrieved successfully",
            401: "Unauthorized - invalid API token",
        }
    )
    @service_api_ns.response(
        200,
        "Annotations retrieved successfully",
        service_api_ns.models[AnnotationList.__name__],
    )
    @service_api_admission()
    def get(self, request_context: ServiceApiRequestContext):
        """List annotations for the application."""
        query = AnnotationListQuery.model_validate(request.args.to_dict(flat=True))

        page = application_services().service_api_annotations.list(
            request_context,
            page=query.page,
            limit=query.limit,
            keyword=query.keyword,
        )
        annotation_models = TypeAdapter(list[Annotation]).validate_python(page.items, from_attributes=True)
        return AnnotationList(
            data=annotation_models,
            has_more=len(page.items) == query.limit,
            limit=query.limit,
            total=page.total,
            page=query.page,
        ).model_dump(mode="json")

    @service_api_ns.doc(
        summary="Create Annotation",
        description=(
            "Creates a new annotation. Annotations provide predefined question-answer pairs that the app "
            "can match and return directly instead of generating a response."
        ),
        tags=["Annotations"],
        responses={
            201: "Annotation created successfully.",
        },
    )
    @service_api_ns.expect(service_api_ns.models[AnnotationCreatePayload.__name__])
    @service_api_ns.doc("create_annotation")
    @service_api_ns.doc(description="Create a new annotation")
    @service_api_ns.doc(
        responses={
            201: "Annotation created successfully",
            401: "Unauthorized - invalid API token",
        }
    )
    @service_api_ns.response(
        HTTPStatus.CREATED,
        "Annotation created successfully",
        service_api_ns.models[Annotation.__name__],
    )
    @service_api_admission()
    def post(self, request_context: ServiceApiRequestContext):
        """Create a new annotation."""
        payload = AnnotationCreatePayload.model_validate(service_api_ns.payload or {})
        annotation = application_services().service_api_annotations.create(
            request_context,
            question=payload.question,
            answer=payload.answer,
        )
        return dump_response(Annotation, annotation), HTTPStatus.CREATED


@service_api_ns.route("/apps/annotations/<uuid:annotation_id>")
class AnnotationUpdateDeleteApi(Resource):
    @service_api_ns.doc(
        summary="Update Annotation",
        description="Updates the question and answer of an existing annotation.",
        tags=["Annotations"],
        responses={
            200: "Annotation updated successfully.",
            403: "`forbidden` : Insufficient permissions to edit annotations.",
            404: "`not_found` : Annotation does not exist.",
        },
    )
    @service_api_ns.expect(service_api_ns.models[AnnotationCreatePayload.__name__])
    @service_api_ns.doc("update_annotation")
    @service_api_ns.doc(description="Update an existing annotation")
    @service_api_ns.doc(params={"annotation_id": "The unique identifier of the annotation to update."})
    @service_api_ns.doc(
        responses={
            200: "Annotation updated successfully",
            401: "Unauthorized - invalid API token",
            403: "Forbidden - insufficient permissions",
            404: "Annotation not found",
        }
    )
    @service_api_ns.response(
        200,
        "Annotation updated successfully",
        service_api_ns.models[Annotation.__name__],
    )
    @service_api_admission()
    def put(self, request_context: ServiceApiRequestContext, annotation_id: UUID):
        """Update an existing annotation."""
        payload = AnnotationCreatePayload.model_validate(service_api_ns.payload or {})
        try:
            annotation = application_services().service_api_annotations.update(
                request_context,
                annotation_id=str(annotation_id),
                question=payload.question,
                answer=payload.answer,
            )
        except ServiceApiAnnotationNotFoundError as error:
            raise NotFound("Annotation not found") from error
        return dump_response(Annotation, annotation)

    @service_api_ns.doc(
        summary="Delete Annotation",
        description="Deletes an annotation and its associated hit history.",
        tags=["Annotations"],
        responses={
            204: "Annotation deleted successfully.",
            403: "`forbidden` : Insufficient permissions to edit annotations.",
            404: "`not_found` : Annotation does not exist.",
        },
    )
    @service_api_ns.doc("delete_annotation")
    @service_api_ns.doc(description="Delete an annotation")
    @service_api_ns.doc(params={"annotation_id": "The unique identifier of the annotation to delete."})
    @service_api_ns.doc(
        responses={
            204: "Annotation deleted successfully",
            401: "Unauthorized - invalid API token",
            403: "Forbidden - insufficient permissions",
            404: "Annotation not found",
        }
    )
    @service_api_admission()
    def delete(self, request_context: ServiceApiRequestContext, annotation_id: UUID):
        """Delete an annotation."""
        try:
            application_services().service_api_annotations.delete(
                request_context,
                annotation_id=str(annotation_id),
            )
        except ServiceApiAnnotationNotFoundError as error:
            raise NotFound("Annotation not found") from error
        return "", 204
