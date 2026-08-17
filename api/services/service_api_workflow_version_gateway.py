"""Deployment-aware adapter for Service API workflow-version entitlement."""

from typing import override

from enums import CloudPlan, DeploymentEdition
from services.billing_service import BillingService
from services.service_api_workflow_version_policy import ServiceApiWorkflowVersionPolicy


class DeploymentServiceApiWorkflowVersionPolicy(ServiceApiWorkflowVersionPolicy):
    def __init__(self, *, deployment_edition: DeploymentEdition) -> None:
        self._deployment_edition = deployment_edition

    @override
    def can_execute_specific_version(self, *, tenant_id: str) -> bool:
        if self._deployment_edition != DeploymentEdition.CLOUD:
            return True

        billing_info = BillingService.get_info(tenant_id, exclude_vector_space=True)
        return not (billing_info["enabled"] and billing_info["subscription"]["plan"] == CloudPlan.SANDBOX)
