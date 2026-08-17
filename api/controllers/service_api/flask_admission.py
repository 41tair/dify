"""Flask transport adapter for Service API admission."""

from collections.abc import Callable
from functools import wraps
from typing import Concatenate, Protocol, cast

from flask import request
from flask_restx.utils import merge
from werkzeug.exceptions import Forbidden, Unauthorized

from controllers.service_api.schema import (
    USER_FETCH_FROM_ATTR,
    USER_FORM_PARAM,
    USER_QUERY_PARAM,
    USER_REQUIRED_ATTR,
)
from core.logging.context import set_identity_context
from extensions.ext_application_services import application_services
from extensions.otel.runtime import enrich_current_span_identity
from machinery.context import ServiceApiRequestContext
from services.entities.service_api_entities import (
    ServiceApiAdmissionRequirement,
    ServiceApiEndUserRequirement,
    ServiceApiEndUserSource,
)
from services.service_api_admission_service import (
    ServiceApiAdmissionError,
    ServiceApiAdmissionFailure,
)


class _RestxDocumentedView(Protocol):
    """Callable view object carrying Flask-RESTX documentation metadata."""

    __apidoc__: dict[str, object]


APP_TOKEN_FORBIDDEN_RESPONSE = {
    403: "Forbidden - token scope, app, dataset, or workspace access denied",
}


def _document_app_token_contract(
    view_func: Callable[..., object],
    end_user: ServiceApiEndUserRequirement | None,
) -> None:
    doc: dict[str, object] = {"responses": APP_TOKEN_FORBIDDEN_RESPONSE}
    if end_user is not None:
        setattr(view_func, USER_FETCH_FROM_ATTR, end_user.source.name)
        setattr(view_func, USER_REQUIRED_ATTR, end_user.required)
        match end_user.source:
            case ServiceApiEndUserSource.QUERY:
                doc["params"] = {"user": {**USER_QUERY_PARAM, "required": end_user.required}}
            case ServiceApiEndUserSource.FORM:
                doc["params"] = {"user": {**USER_FORM_PARAM, "required": end_user.required}}
            case ServiceApiEndUserSource.JSON:
                pass

    cast(_RestxDocumentedView, view_func).__apidoc__ = cast(
        dict[str, object],
        merge(getattr(view_func, "__apidoc__", {}), doc),
    )


def _parse_bearer_token() -> str:
    auth_header = request.headers.get("Authorization")
    if auth_header is None:
        raise Unauthorized("Authorization header must be provided and start with 'Bearer'")

    parts = auth_header.split(None, 1)
    if len(parts) != 2 or not parts[1]:
        raise Unauthorized("Authorization header must be provided and start with 'Bearer'")
    auth_scheme, auth_token = parts
    if auth_scheme.lower() != "bearer":
        raise Unauthorized("Authorization scheme must be 'Bearer'")
    return auth_token


def _extract_end_user_external_id(requirement: ServiceApiEndUserRequirement | None) -> str | None:
    if requirement is None:
        return None

    match requirement.source:
        case ServiceApiEndUserSource.QUERY:
            user_id = request.args.get("user")
        case ServiceApiEndUserSource.JSON:
            payload = request.get_json(silent=True) or {}
            user_id = payload.get("user") if isinstance(payload, dict) else None
        case ServiceApiEndUserSource.FORM:
            user_id = request.form.get("user")

    return str(user_id) if user_id else None


def _admit_app_request(*, requirement: ServiceApiAdmissionRequirement) -> ServiceApiRequestContext:
    end_user_external_id = _extract_end_user_external_id(requirement.end_user)

    try:
        return application_services().service_api_admission.admit(
            token=_parse_bearer_token(),
            requirement=requirement,
            end_user_external_id=end_user_external_id,
        )
    except ServiceApiAdmissionError as error:
        match error.failure:
            case ServiceApiAdmissionFailure.TOKEN_INVALID:
                raise Unauthorized("Access token is invalid") from error
            case ServiceApiAdmissionFailure.END_USER_REQUIRED:
                raise ValueError("Arg user must be provided.") from error
            case ServiceApiAdmissionFailure.APP_NOT_FOUND:
                raise Forbidden("The app no longer exists.") from error
            case ServiceApiAdmissionFailure.APP_STATUS_ABNORMAL:
                raise Forbidden("The app's status is abnormal.") from error
            case ServiceApiAdmissionFailure.APP_API_DISABLED:
                raise Forbidden("The app's API service has been disabled.") from error
            case ServiceApiAdmissionFailure.TENANT_NOT_FOUND:
                raise ValueError("Tenant does not exist.") from error
            case ServiceApiAdmissionFailure.TENANT_ARCHIVED:
                raise Forbidden("The workspace's status is archived.") from error
            case ServiceApiAdmissionFailure.TENANT_OWNER_NOT_FOUND:
                raise Unauthorized("Tenant owner account not found or tenant is not active.") from error
            case _:
                raise RuntimeError("Unhandled Service API App admission failure") from error


def _enrich_request_identity(context: ServiceApiRequestContext) -> None:
    if context.end_user is None:
        actor_id = context.app_id
        actor_type = "service-api-app"
    else:
        actor_id = context.end_user.id
        actor_type = "service-api-end-user"

    set_identity_context(
        tenant_id=context.tenant_id,
        user_id=actor_id,
        user_type=actor_type,
    )
    enrich_current_span_identity(
        tenant_id=context.tenant_id,
        app_id=context.app_id,
        actor_id=actor_id,
        actor_type=actor_type,
    )


def service_api_admission[T, **P, R](
    *,
    end_user: ServiceApiEndUserRequirement | None = None,
    require_tenant_owner: bool | None = None,
) -> Callable[
    [Callable[Concatenate[T, ServiceApiRequestContext, P], R]],
    Callable[Concatenate[T, P], R],
]:
    """Declare Service API admission and inject a framework-neutral context."""

    requirement = ServiceApiAdmissionRequirement(
        end_user=end_user,
        require_tenant_owner=(end_user is None if require_tenant_owner is None else require_tenant_owner),
    )

    def decorator(
        view: Callable[Concatenate[T, ServiceApiRequestContext, P], R],
    ) -> Callable[Concatenate[T, P], R]:
        @wraps(view)
        def inject_request_context(self: T, /, *args: P.args, **kwargs: P.kwargs) -> R:
            context = _admit_app_request(requirement=requirement)
            _enrich_request_identity(context)
            return view(self, context, *args, **kwargs)

        _document_app_token_contract(inject_request_context, end_user=end_user)
        return inject_request_context

    return decorator
