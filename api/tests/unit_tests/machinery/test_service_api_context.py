from dataclasses import FrozenInstanceError, fields, is_dataclass

import pytest

from machinery.context import ServiceApiEndUserIdentity, ServiceApiRequestContext


def test_service_api_context_is_minimal_immutable_data() -> None:
    context = ServiceApiRequestContext(
        tenant_id="tenant-1",
        app_id="app-1",
        app_mode="chat",
        end_user=ServiceApiEndUserIdentity(id="end-user-1", external_user_id="external-1"),
    )

    assert is_dataclass(context)
    assert [field.name for field in fields(context)] == ["tenant_id", "app_id", "app_mode", "end_user"]
    with pytest.raises(FrozenInstanceError):
        context.app_id = "other"  # type: ignore[misc]
