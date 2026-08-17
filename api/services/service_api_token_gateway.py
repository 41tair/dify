"""API-token adapter used by Service API admission."""

from typing import override

from werkzeug.exceptions import Unauthorized

from services.api_token_service import ApiTokenCache, fetch_token_with_single_flight, record_token_usage
from services.entities.service_api_entities import ResolvedServiceApiCredential
from services.service_api_admission_service import ServiceApiTokenGateway


class CachedServiceApiTokenGateway(ServiceApiTokenGateway):
    @override
    def resolve(self, token: str) -> ResolvedServiceApiCredential | None:
        cached_token = ApiTokenCache.get(token, "app")
        if cached_token is not None:
            record_token_usage(token, "app")
            api_token = cached_token
        else:
            try:
                api_token = fetch_token_with_single_flight(token, "app")
            except Unauthorized:
                return None

        if not api_token.app_id:
            return None
        return ResolvedServiceApiCredential(
            app_id=str(api_token.app_id),
            tenant_id=str(api_token.tenant_id) if api_token.tenant_id else None,
        )
