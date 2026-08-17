from flask_restx import Resource
from werkzeug.exceptions import Forbidden

from controllers.common.fields import Site as SiteResponse
from controllers.common.schema import register_response_schema_models
from controllers.service_api import service_api_ns
from controllers.service_api.flask_admission import service_api_admission
from extensions.ext_application_services import application_services
from machinery.context import ServiceApiRequestContext
from services.service_api_site_service import ServiceApiSiteForbiddenError

register_response_schema_models(service_api_ns, SiteResponse)


@service_api_ns.route("/site")
class AppSiteApi(Resource):
    """Resource for app sites."""

    @service_api_ns.doc(
        summary="Get App WebApp Settings",
        description=(
            "Retrieve the WebApp settings of this application, including site configuration, theme, and "
            "customization options."
        ),
        tags=["Applications"],
        responses={
            200: "WebApp settings of the application.",
            403: "`forbidden` : Site not found for this application or the workspace has been archived.",
        },
    )
    @service_api_ns.doc("get_app_site")
    @service_api_ns.doc(description="Get application site configuration")
    @service_api_ns.doc(
        responses={
            200: "Site configuration retrieved successfully",
            401: "Unauthorized - invalid API token",
            403: "Forbidden - site not found or tenant archived",
        }
    )
    @service_api_ns.response(
        200,
        "Site configuration retrieved successfully",
        service_api_ns.models[SiteResponse.__name__],
    )
    @service_api_admission()
    def get(self, request_context: ServiceApiRequestContext):
        """Retrieve app site info.

        Returns the site configuration for the application including theme, icons, and text.
        """
        try:
            site = application_services().service_api_sites.get_site(request_context)
        except ServiceApiSiteForbiddenError as error:
            raise Forbidden() from error
        return SiteResponse.model_validate(site, from_attributes=True).model_dump(mode="json")
