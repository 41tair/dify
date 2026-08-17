"""Application service for Service API human-input use cases."""

from collections.abc import Mapping
from typing import Any, Protocol

from machinery.context import ServiceApiRequestContext


class ServiceApiHumanInputNotFoundError(ValueError):
    pass


class ServiceApiHumanInputInvalidRecipientError(ValueError):
    pass


class ServiceApiHumanInputGateway(Protocol):
    def get_form(self, context: ServiceApiRequestContext, *, form_token: str) -> dict[str, Any]: ...

    def submit_form(
        self,
        context: ServiceApiRequestContext,
        *,
        form_token: str,
        action: str,
        inputs: Mapping[str, Any],
    ) -> None: ...


class ServiceApiHumanInputService:
    def __init__(self, *, forms: ServiceApiHumanInputGateway) -> None:
        self._forms = forms

    def get_form(self, context: ServiceApiRequestContext, *, form_token: str) -> dict[str, Any]:
        return self._forms.get_form(context, form_token=form_token)

    def submit_form(
        self,
        context: ServiceApiRequestContext,
        *,
        form_token: str,
        action: str,
        inputs: Mapping[str, Any],
    ) -> None:
        self._forms.submit_form(
            context,
            form_token=form_token,
            action=action,
            inputs=inputs,
        )
