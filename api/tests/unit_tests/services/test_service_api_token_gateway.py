from types import SimpleNamespace
from unittest.mock import patch

from werkzeug.exceptions import Unauthorized

from services.entities.service_api_entities import ResolvedServiceApiCredential
from services.service_api_token_gateway import CachedServiceApiTokenGateway


def test_cached_token_resolves_plain_credential_without_database_lookup() -> None:
    cached = SimpleNamespace(app_id="app-1", tenant_id="tenant-1")

    with (
        patch("services.service_api_token_gateway.ApiTokenCache.get", return_value=cached) as cache_get,
        patch("services.service_api_token_gateway.fetch_token_with_single_flight") as fetch,
        patch("services.service_api_token_gateway.record_token_usage") as record_usage,
    ):
        credential = CachedServiceApiTokenGateway().resolve("token")

    assert credential == ResolvedServiceApiCredential(app_id="app-1", tenant_id="tenant-1")
    cache_get.assert_called_once_with("token", "app")
    fetch.assert_not_called()
    record_usage.assert_called_once_with("token", "app")


def test_cache_miss_uses_existing_single_flight_token_lookup() -> None:
    token = SimpleNamespace(app_id="app-1", tenant_id="tenant-1")

    with (
        patch("services.service_api_token_gateway.ApiTokenCache.get", return_value=None),
        patch("services.service_api_token_gateway.fetch_token_with_single_flight", return_value=token) as fetch,
        patch("services.service_api_token_gateway.record_token_usage") as record_usage,
    ):
        credential = CachedServiceApiTokenGateway().resolve("token")

    assert credential == ResolvedServiceApiCredential(app_id="app-1", tenant_id="tenant-1")
    fetch.assert_called_once_with("token", "app")
    record_usage.assert_not_called()


def test_invalid_or_non_app_token_is_not_admitted() -> None:
    gateway = CachedServiceApiTokenGateway()
    with (
        patch("services.service_api_token_gateway.ApiTokenCache.get", return_value=None),
        patch(
            "services.service_api_token_gateway.fetch_token_with_single_flight",
            side_effect=Unauthorized(),
        ),
    ):
        assert gateway.resolve("invalid") is None

    with (
        patch("services.service_api_token_gateway.ApiTokenCache.get", return_value=None),
        patch(
            "services.service_api_token_gateway.fetch_token_with_single_flight",
            return_value=SimpleNamespace(app_id=None, tenant_id="tenant-1"),
        ),
    ):
        assert gateway.resolve("dataset-token") is None
