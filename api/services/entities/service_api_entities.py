"""Framework- and persistence-neutral contracts for Service API admission."""

from dataclasses import dataclass
from enum import StrEnum, auto

from machinery.context import ServiceApiEndUserIdentity


class ServiceApiEndUserSource(StrEnum):
    QUERY = auto()
    JSON = auto()
    FORM = auto()


@dataclass(frozen=True, slots=True, kw_only=True)
class ServiceApiEndUserRequirement:
    source: ServiceApiEndUserSource
    required: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class ServiceApiAdmissionRequirement:
    end_user: ServiceApiEndUserRequirement | None = None
    require_tenant_owner: bool = True


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedServiceApiCredential:
    app_id: str
    tenant_id: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ServiceApiAdmissionSnapshot:
    app_id: str
    tenant_id: str
    app_mode: str
    app_status: str
    api_enabled: bool
    tenant_status: str | None
    tenant_owner_exists: bool
    end_user: ServiceApiEndUserIdentity | None
