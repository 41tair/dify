from unittest.mock import create_autospec

import pytest

from machinery.context import ServiceApiRequestContext
from services.end_user_query_service import EndUserNotFoundError, EndUserQuery, EndUserQueryService
from services.entities.end_user_entities import EndUserRecord


def _request_context() -> ServiceApiRequestContext:
    return ServiceApiRequestContext(
        tenant_id="tenant-1",
        app_id="app-1",
    )


def test_get_by_id_scopes_repository_query_to_admitted_app() -> None:
    context = _request_context()
    end_users = create_autospec(EndUserQuery, instance=True, spec_set=True)
    record = create_autospec(EndUserRecord, instance=True, spec_set=True)
    end_users.find_by_id.return_value = record

    result = EndUserQueryService(end_users=end_users).get_by_id(context, "end-user-1")

    assert result is record
    end_users.find_by_id.assert_called_once_with(
        tenant_id="tenant-1",
        app_id="app-1",
        end_user_id="end-user-1",
    )


def test_get_by_id_raises_when_repository_has_no_visible_record() -> None:
    context = _request_context()
    end_users = create_autospec(EndUserQuery, instance=True, spec_set=True)
    end_users.find_by_id.return_value = None

    with pytest.raises(EndUserNotFoundError):
        EndUserQueryService(end_users=end_users).get_by_id(context, "missing")
