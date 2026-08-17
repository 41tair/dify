"""Infrastructure adapter for Service API human-input use cases."""

from collections.abc import Mapping
from typing import Any, override

from sqlalchemy.orm import Session, sessionmaker

from core.workflow.human_input_policy import HumanInputSurface, is_recipient_type_allowed_for_surface
from libs.helper import to_timestamp
from machinery.context import ServiceApiRequestContext
from services.entities.human_input_entities import stringify_form_default_values
from services.human_input_service import FormNotFoundError, HumanInputService, WebAppDeliveryNotEnabledError
from services.service_api_human_input_service import (
    ServiceApiHumanInputGateway,
    ServiceApiHumanInputInvalidRecipientError,
    ServiceApiHumanInputNotFoundError,
)


class DefaultServiceApiHumanInputGateway(ServiceApiHumanInputGateway):
    def __init__(self, *, session_factory: sessionmaker[Session]) -> None:
        self._service = HumanInputService(session_factory)

    @staticmethod
    def _require_form(context: ServiceApiRequestContext, service: HumanInputService, form_token: str):
        form = service.get_form_by_token(form_token)
        if (
            form is None
            or form.app_id != context.app_id
            or form.tenant_id != context.tenant_id
            or not is_recipient_type_allowed_for_surface(form.recipient_type, HumanInputSurface.SERVICE_API)
        ):
            raise ServiceApiHumanInputNotFoundError()
        return form

    @override
    def get_form(self, context: ServiceApiRequestContext, *, form_token: str) -> dict[str, Any]:
        form = self._require_form(context, self._service, form_token)
        self._service.ensure_form_active(form)
        inputs = self._service.resolve_form_inputs(form)
        definition = form.get_definition().model_dump(mode="json")
        return {
            "form_content": definition["rendered_content"],
            "inputs": [form_input.model_dump(mode="json") for form_input in inputs],
            "resolved_default_values": stringify_form_default_values(definition["default_values"]),
            "user_actions": definition["user_actions"],
            "expiration_time": to_timestamp(form.expiration_time),
        }

    @override
    def submit_form(
        self,
        context: ServiceApiRequestContext,
        *,
        form_token: str,
        action: str,
        inputs: Mapping[str, Any],
    ) -> None:
        if context.end_user is None:
            raise RuntimeError("Human-input submission requires an EndUser")
        form = self._require_form(context, self._service, form_token)
        recipient_type = form.recipient_type
        if recipient_type is None:
            raise ServiceApiHumanInputInvalidRecipientError()
        try:
            self._service.submit_form_by_token(
                recipient_type=recipient_type,
                form_token=form_token,
                selected_action_id=action,
                form_data=inputs,
                submission_end_user_id=context.end_user.id,
            )
        except (FormNotFoundError, WebAppDeliveryNotEnabledError) as error:
            raise ServiceApiHumanInputNotFoundError() from error
