import logging
from urllib.parse import quote
from uuid import UUID

from flask import Response, request
from flask_restx import Resource
from pydantic import BaseModel, Field

from controllers.common.fields import BinaryFileResponse
from controllers.common.file_response import enforce_download_for_html
from controllers.common.schema import query_params_from_model, register_response_schema_model, register_schema_model
from controllers.service_api import service_api_ns
from controllers.service_api.app.error import (
    FileAccessDeniedError,
    FileNotFoundError,
)
from controllers.service_api.flask_admission import service_api_admission
from controllers.service_api.schema import binary_response
from extensions.ext_application_services import application_services
from machinery.context import ServiceApiRequestContext
from services.entities.service_api_entities import ServiceApiEndUserRequirement, ServiceApiEndUserSource
from services.service_api_file_service import (
    ServiceApiFileAccessDeniedError,
    ServiceApiFileNotFoundError,
    ServiceApiFilePreview,
)

logger = logging.getLogger(__name__)


class FilePreviewQuery(BaseModel):
    as_attachment: bool = Field(
        default=False,
        description="If `true`, forces the file to download as an attachment instead of previewing in browser.",
    )


register_schema_model(service_api_ns, FilePreviewQuery)
register_response_schema_model(service_api_ns, BinaryFileResponse)

FILE_PREVIEW_RESPONSE_MEDIA_TYPES = [
    "application/octet-stream",
    "application/pdf",
    "audio/aac",
    "audio/flac",
    "audio/mp4",
    "audio/mpeg",
    "audio/ogg",
    "audio/wav",
    "audio/x-m4a",
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
    "text/plain",
    "video/mp4",
    "video/quicktime",
    "video/webm",
]


@service_api_ns.route("/files/<uuid:file_id>/preview")
class FilePreviewApi(Resource):
    """
    Service API File Preview endpoint

    Provides secure file preview/download functionality for external API users.
    Files can only be accessed if they belong to messages within the requesting app's context.
    """

    @service_api_ns.doc(
        summary="Download File",
        description=(
            "Preview or download uploaded files previously uploaded via the [Upload "
            "File](/api-reference/files/upload-file) API. Files can only be accessed if they belong to "
            "messages within the requesting application."
        ),
        tags=["Files"],
        responses={
            200: (
                "Returns the raw file content. The `Content-Type` header is set to the file's MIME type. If "
                "`as_attachment` is `true`, the file is returned as a download with `Content-Disposition: "
                "attachment`."
            ),
            403: "`file_access_denied` : Access to the requested file is denied.",
            404: "`file_not_found` : The requested file was not found.",
        },
    )
    @service_api_ns.doc(params=query_params_from_model(FilePreviewQuery))
    @binary_response(service_api_ns, FILE_PREVIEW_RESPONSE_MEDIA_TYPES)
    @service_api_ns.doc("preview_file")
    @service_api_ns.doc(description="Preview or download a file uploaded via Service API")
    @service_api_ns.doc(
        params={
            "file_id": (
                "The unique identifier of the file to preview, obtained from the "
                "[Upload File](/api-reference/files/upload-file) API response."
            )
        }
    )
    @service_api_ns.doc(
        responses={
            200: "File retrieved successfully",
            401: "Unauthorized - invalid API token",
            403: "Forbidden - file access denied",
            404: "File not found",
        }
    )
    @service_api_ns.response(200, "File retrieved successfully")
    @service_api_admission(end_user=ServiceApiEndUserRequirement(source=ServiceApiEndUserSource.QUERY))
    def get(self, request_context: ServiceApiRequestContext, file_id: UUID):
        """
        Preview/Download a file that was uploaded via Service API.

        Provides secure file preview/download functionality.
        Files can only be accessed if they belong to messages within the requesting app's context.
        """
        file_id_str = str(file_id)

        # Parse query parameters
        args = FilePreviewQuery.model_validate(request.args.to_dict())

        try:
            preview = application_services().service_api_files.preview(request_context, file_id=file_id_str)
        except ServiceApiFileNotFoundError as error:
            raise FileNotFoundError("File not found") from error
        except ServiceApiFileAccessDeniedError as error:
            raise FileAccessDeniedError("File access denied") from error

        # Build response with appropriate headers
        response = self._build_file_response(preview, args.as_attachment)

        return response

    def _build_file_response(self, preview: ServiceApiFilePreview, as_attachment: bool = False) -> Response:
        """
        Build Flask Response object with appropriate headers for file streaming

        Args:
            generator: File content generator from storage
            upload_file: UploadFile database record
            as_attachment: Whether to set Content-Disposition as attachment

        Returns:
            Flask Response object with streaming file content
        """
        response = Response(
            preview.body,
            mimetype=preview.mime_type,
            direct_passthrough=True,
            headers={},
        )

        # Add Content-Length if known
        if preview.size > 0:
            response.headers["Content-Length"] = str(preview.size)

        # Add Accept-Ranges header for audio/video files to support seeking
        if preview.mime_type in [
            "audio/mpeg",
            "audio/wav",
            "audio/mp4",
            "audio/ogg",
            "audio/flac",
            "audio/aac",
            "video/mp4",
            "video/webm",
            "video/quicktime",
            "audio/x-m4a",
        ]:
            response.headers["Accept-Ranges"] = "bytes"

        # Set Content-Disposition for downloads
        if as_attachment and preview.name:
            encoded_filename = quote(preview.name)
            response.headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{encoded_filename}"
            # Override content-type for downloads to force download
            response.headers["Content-Type"] = "application/octet-stream"

        enforce_download_for_html(
            response,
            mime_type=preview.mime_type,
            filename=preview.name,
            extension=preview.extension,
        )

        # Add caching headers for performance
        response.headers["Cache-Control"] = "public, max-age=3600"  # Cache for 1 hour

        return response
