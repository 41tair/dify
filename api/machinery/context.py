"""Stable values passed from API admission into application services."""

from dataclasses import dataclass
from typing import NamedTuple


class RequestContext(NamedTuple):
    request_id: str
    trace_id: str | None
    account_id: str
    active_workspace_id: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ServiceApiEndUserIdentity:
    """Stable EndUser identity admitted for a Service API request."""

    id: str
    external_user_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ServiceApiRequestContext:
    """Stable application identity admitted from a Service API request."""

    tenant_id: str
    app_id: str
    app_mode: str | None = None
    end_user: ServiceApiEndUserIdentity | None = None
