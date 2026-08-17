"""Application service for reading Service API site settings."""

from dataclasses import dataclass
from typing import Protocol

from machinery.context import ServiceApiRequestContext


@dataclass(frozen=True, slots=True, kw_only=True)
class ServiceApiSite:
    title: str
    chat_color_theme: str | None
    chat_color_theme_inverted: bool
    icon_type: str | None
    icon: str | None
    icon_background: str | None
    description: str | None
    copyright: str | None
    privacy_policy: str | None
    input_placeholder: str | None
    custom_disclaimer: str | None
    default_language: str
    show_workflow_steps: bool
    use_icon_as_answer_icon: bool


class ServiceApiSiteForbiddenError(ValueError):
    pass


class ServiceApiSiteGateway(Protocol):
    def get_site(self, context: ServiceApiRequestContext) -> ServiceApiSite: ...


class ServiceApiSiteService:
    def __init__(self, *, sites: ServiceApiSiteGateway) -> None:
        self._sites = sites

    def get_site(self, context: ServiceApiRequestContext) -> ServiceApiSite:
        return self._sites.get_site(context)
