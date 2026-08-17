from datetime import UTC, datetime
from inspect import unwrap
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from controllers.service_api.end_user.end_user import EndUserApi
from controllers.service_api.end_user.error import EndUserNotFoundError
from fields.end_user_fields import EndUserDetail
from machinery.context import ServiceApiRequestContext
from services.end_user_query_service import EndUserNotFoundError as EndUserNotFoundApplicationError
from services.entities.end_user_entities import EndUserRecord


def _request_context() -> ServiceApiRequestContext:
    return ServiceApiRequestContext(
        tenant_id=str(uuid4()),
        app_id=str(uuid4()),
    )


class TestEndUserApi:
    def test_response_schema_exposes_only_public_anonymous_field(self) -> None:
        properties = EndUserDetail.model_json_schema()["properties"]

        assert "is_anonymous" in properties
        assert "_is_anonymous" not in properties

    def test_get_end_user_returns_all_attributes(self) -> None:
        request_context = _request_context()
        end_user_id = uuid4()
        end_user = EndUserRecord(
            id=str(end_user_id),
            tenant_id=request_context.tenant_id,
            app_id=request_context.app_id,
            type="service-api",
            external_user_id="external-123",
            name="Alice",
            is_anonymous=True,
            session_id="session-xyz",
            created_at=datetime(2024, 1, 1, tzinfo=UTC),
            updated_at=datetime(2024, 1, 2, tzinfo=UTC),
        )
        queries = MagicMock()
        queries.get_by_id.return_value = end_user
        services = SimpleNamespace(end_user_queries=queries)

        with patch("controllers.service_api.end_user.end_user.application_services", return_value=services):
            result = unwrap(EndUserApi.get)(EndUserApi(), request_context, end_user_id)

        queries.get_by_id.assert_called_once_with(request_context, str(end_user_id))
        assert result == {
            "id": end_user.id,
            "tenant_id": end_user.tenant_id,
            "app_id": end_user.app_id,
            "type": end_user.type,
            "external_user_id": end_user.external_user_id,
            "name": end_user.name,
            "is_anonymous": True,
            "session_id": end_user.session_id,
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-02T00:00:00Z",
        }

    def test_get_end_user_translates_not_found(self) -> None:
        request_context = _request_context()
        end_user_id = uuid4()
        queries = MagicMock()
        queries.get_by_id.side_effect = EndUserNotFoundApplicationError(str(end_user_id))
        services = SimpleNamespace(end_user_queries=queries)

        with (
            patch("controllers.service_api.end_user.end_user.application_services", return_value=services),
            pytest.raises(EndUserNotFoundError),
        ):
            unwrap(EndUserApi.get)(EndUserApi(), request_context, end_user_id)
