from uuid import UUID

from flask_restx import Resource

from controllers.common.schema import register_response_schema_models
from controllers.service_api import service_api_ns
from controllers.service_api.end_user.error import EndUserNotFoundError
from controllers.service_api.flask_admission import service_api_admission
from extensions.ext_application_services import application_services
from fields.end_user_fields import EndUserDetail
from machinery.context import ServiceApiRequestContext
from services.end_user_query_service import EndUserNotFoundError as EndUserNotFoundApplicationError

register_response_schema_models(service_api_ns, EndUserDetail)


@service_api_ns.route("/end-users/<uuid:end_user_id>")
class EndUserApi(Resource):
    """Resource for retrieving end user details by ID."""

    @service_api_ns.doc(
        summary="Get End User Info",
        description=(
            "Retrieve an end user by ID. Useful when other APIs return an end-user ID (e.g., "
            "`created_by` from [Upload File](/api-reference/files/upload-file))."
        ),
        tags=["End Users"],
        responses={
            200: "End user retrieved successfully.",
            404: "`end_user_not_found` : End user not found.",
        },
    )
    @service_api_ns.doc("get_end_user")
    @service_api_ns.doc(description="Get an end user by ID")
    @service_api_ns.doc(
        params={"end_user_id": "End user ID"},
        responses={
            200: "End user retrieved successfully",
            401: "Unauthorized - invalid API token",
            404: "End user not found",
        },
    )
    @service_api_ns.response(200, "End user retrieved successfully", service_api_ns.models[EndUserDetail.__name__])
    @service_api_admission()
    def get(self, request_context: ServiceApiRequestContext, end_user_id: UUID):
        """Get end user detail.

        This endpoint is scoped to the current app token's tenant/app to prevent
        cross-tenant/app access when an end-user ID is known.
        """

        try:
            end_user = application_services().end_user_queries.get_by_id(request_context, str(end_user_id))
        except EndUserNotFoundApplicationError as error:
            raise EndUserNotFoundError() from error

        return EndUserDetail.model_validate(end_user).model_dump(mode="json")
