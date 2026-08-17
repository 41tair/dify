import inspect
import logging
import time
from collections.abc import Callable
from functools import wraps
from typing import cast

from flask import current_app, request
from flask_login import user_logged_in
from flask_restx import Resource
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from werkzeug.exceptions import Forbidden, NotFound, ServiceUnavailable, Unauthorized

from configs import dify_config
from enums import CloudPlan, DeploymentEdition
from extensions.ext_database import db
from extensions.ext_redis import redis_client
from libs.login import current_user
from models import Account, Tenant, TenantAccountJoin, TenantStatus
from models.dataset import Dataset, RateLimitLog
from models.model import ApiToken
from services.api_token_service import ApiTokenCache, fetch_token_with_single_flight, record_token_usage
from services.feature_service import FeatureService

logger = logging.getLogger(__name__)


DATASET_TOKEN_AUTH_RESPONSES = {
    401: "Unauthorized - invalid API token",
    403: "Forbidden - dataset API access or workspace access denied",
}


def cloud_edition_billing_resource_check[**P, R](
    resource: str,
    api_token_type: str,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    def interceptor(view: Callable[P, R]):
        def decorated(*args: P.args, **kwargs: P.kwargs):
            api_token = validate_and_get_api_token(api_token_type)
            if resource == "vector_space":
                if dify_config.DEPLOYMENT_EDITION != DeploymentEdition.CLOUD:
                    return view(*args, **kwargs)

                vector_space = FeatureService.get_vector_space(api_token.tenant_id)
                if vector_space.usage_unknown:
                    features = FeatureService.get_features(api_token.tenant_id, exclude_vector_space=True)
                    if features.billing.enabled and features.billing.subscription.plan == CloudPlan.SANDBOX:
                        raise ServiceUnavailable(
                            "Unable to verify vector space usage right now. Please try again later."
                        )
                if 0 < vector_space.limit <= vector_space.size:
                    raise Forbidden("The capacity of the vector space has reached the limit of your subscription.")
                return view(*args, **kwargs)

            features = FeatureService.get_features(api_token.tenant_id, exclude_vector_space=True)

            if features.billing.enabled:
                members = features.members
                apps = features.apps
                documents_upload_quota = features.documents_upload_quota

                if resource == "members" and 0 < members.limit <= members.size:
                    raise Forbidden("The number of members has reached the limit of your subscription.")
                elif resource == "apps" and 0 < apps.limit <= apps.size:
                    raise Forbidden("The number of apps has reached the limit of your subscription.")
                elif resource == "documents" and 0 < documents_upload_quota.limit <= documents_upload_quota.size:
                    raise Forbidden("The number of documents has reached the limit of your subscription.")
                else:
                    return view(*args, **kwargs)

            return view(*args, **kwargs)

        return decorated

    return interceptor


def cloud_edition_billing_knowledge_limit_check[**P, R](
    resource: str,
    api_token_type: str,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    def interceptor(view: Callable[P, R]):
        @wraps(view)
        def decorated(*args: P.args, **kwargs: P.kwargs):
            api_token = validate_and_get_api_token(api_token_type)
            features = FeatureService.get_features(api_token.tenant_id, exclude_vector_space=True)
            if features.billing.enabled:
                if resource == "add_segment":
                    if features.billing.subscription.plan == CloudPlan.SANDBOX:
                        raise Forbidden(
                            "To unlock this feature and elevate your Dify experience, please upgrade to a paid plan."
                        )
                else:
                    return view(*args, **kwargs)

            return view(*args, **kwargs)

        return decorated

    return interceptor


def cloud_edition_billing_rate_limit_check[**P, R](
    resource: str,
    api_token_type: str,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    def interceptor(view: Callable[P, R]):
        @wraps(view)
        def decorated(*args: P.args, **kwargs: P.kwargs):
            api_token = validate_and_get_api_token(api_token_type)

            if resource == "knowledge":
                knowledge_rate_limit = FeatureService.get_knowledge_rate_limit(api_token.tenant_id)
                if knowledge_rate_limit.enabled:
                    current_time = int(time.time() * 1000)
                    key = f"rate_limit_{api_token.tenant_id}"

                    redis_client.zadd(key, {current_time: current_time})

                    redis_client.zremrangebyscore(key, 0, current_time - 60000)

                    request_count = redis_client.zcard(key)

                    if request_count > knowledge_rate_limit.limit:
                        # add ratelimit record
                        rate_limit_log = RateLimitLog(
                            tenant_id=api_token.tenant_id,
                            subscription_plan=knowledge_rate_limit.subscription_plan,
                            operation="knowledge",
                        )
                        with sessionmaker(bind=db.engine, expire_on_commit=False).begin() as session:
                            session.add(rate_limit_log)
                        raise Forbidden(
                            "Sorry, you have reached the knowledge base request rate limit of your subscription."
                        )
            return view(*args, **kwargs)

        return decorated

    return interceptor


def validate_dataset_token[R](view: Callable[..., R]) -> Callable[..., R]:
    positional_parameters = [
        parameter
        for parameter in inspect.signature(view).parameters.values()
        if parameter.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    expects_bound_instance = bool(positional_parameters and positional_parameters[0].name in {"self", "cls"})

    @wraps(view)
    def decorated(*args: object, **kwargs: object) -> R:
        api_token = validate_and_get_api_token("dataset")

        # Flask may pass URL path parameters positionally, so inspect both kwargs and args.
        dataset_id = kwargs.get("dataset_id")

        if not dataset_id and args:
            potential_id = args[0]
            try:
                str_id = str(potential_id)
                if len(str_id) == 36 and str_id.count("-") == 4:
                    dataset_id = str_id
            except Exception:
                logger.exception("Failed to parse dataset_id from positional args")

        if dataset_id:
            dataset_id = str(dataset_id)
            dataset = db.session.scalar(
                select(Dataset)
                .where(
                    Dataset.id == dataset_id,
                    Dataset.tenant_id == api_token.tenant_id,
                )
                .limit(1)
            )
            if not dataset:
                raise NotFound("Dataset not found.")
            if not dataset.enable_api:
                raise Forbidden("Dataset api access is not enabled.")

        tenant_account_join = db.session.execute(
            select(Tenant, TenantAccountJoin).where(
                Tenant.id == api_token.tenant_id,
                TenantAccountJoin.tenant_id == Tenant.id,
                TenantAccountJoin.role.in_(["owner"]),
                Tenant.status == TenantStatus.NORMAL,
            )
        ).one_or_none()  # TODO: only owner information is required, so only one is returned.
        if tenant_account_join:
            tenant, ta = tenant_account_join
            account = db.session.get(Account, ta.account_id)
            # Login admin
            if account:
                account.set_current_tenant_with_session(tenant, session=db.session())
                current_app.login_manager._update_request_context_with_user(account)  # type: ignore
                user_logged_in.send(current_app._get_current_object(), user=current_user)  # type: ignore
            else:
                raise Unauthorized("Tenant owner account does not exist.")
        else:
            raise Unauthorized("Tenant does not exist.")

        if expects_bound_instance:
            if not args:
                raise TypeError("validate_dataset_token expected a bound resource instance.")
            return view(args[0], api_token.tenant_id, *args[1:], **kwargs)

        return view(api_token.tenant_id, *args, **kwargs)

    return decorated


def validate_and_get_api_token(scope: str | None = None):
    """
    Validate and get API token with Redis caching.

    This function uses a two-tier approach:
    1. First checks Redis cache for the token
    2. If not cached, queries database and caches the result

    The last_used_at field is updated asynchronously via Celery task
    to avoid blocking the request.
    """

    auth_header = request.headers.get("Authorization")
    if auth_header is None or " " not in auth_header:
        raise Unauthorized("Authorization header must be provided and start with 'Bearer'")

    auth_scheme, auth_token = auth_header.split(None, 1)
    auth_scheme = auth_scheme.lower()

    if auth_scheme != "bearer":
        raise Unauthorized("Authorization scheme must be 'Bearer'")

    # Try to get token from cache first
    # Returns a CachedApiToken (plain Python object), not a SQLAlchemy model
    cached_token = ApiTokenCache.get(auth_token, scope)
    if cached_token is not None:
        logger.debug("Token validation served from cache for scope: %s", scope)
        # Record usage in Redis for later batch update (no Celery task per request)
        record_token_usage(auth_token, scope)
        return cast(ApiToken, cached_token)

    # Cache miss - use Redis lock for single-flight mode
    # This ensures only one request queries DB for the same token concurrently
    return fetch_token_with_single_flight(auth_token, scope)


class DatasetApiResource(Resource):
    __apidoc__ = {"responses": DATASET_TOKEN_AUTH_RESPONSES}

    method_decorators = [validate_dataset_token]

    def get_dataset(self, dataset_id: str, tenant_id: str) -> Dataset:
        dataset = db.session.scalar(
            select(Dataset).where(Dataset.id == dataset_id, Dataset.tenant_id == tenant_id).limit(1)
        )

        if not dataset:
            raise NotFound("Dataset not found.")

        return dataset
