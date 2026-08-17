"""Application port for Service API workflow-version entitlement."""

from typing import Protocol


class ServiceApiWorkflowVersionPolicy(Protocol):
    def can_execute_specific_version(self, *, tenant_id: str) -> bool: ...
