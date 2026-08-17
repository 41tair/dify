"""SQLAlchemy adapter for Service API site settings."""

from typing import override

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from machinery.context import ServiceApiRequestContext
from models.model import App, Site
from services.service_api_site_service import (
    ServiceApiSite,
    ServiceApiSiteForbiddenError,
    ServiceApiSiteGateway,
)


class SqlAlchemyServiceApiSiteGateway(ServiceApiSiteGateway):
    def __init__(self, *, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    @override
    def get_site(self, context: ServiceApiRequestContext) -> ServiceApiSite:
        with self._session_factory() as session:
            site = session.scalar(
                select(Site)
                .join(App, App.id == Site.app_id)
                .where(
                    Site.app_id == context.app_id,
                    App.tenant_id == context.tenant_id,
                )
            )
            if site is None:
                raise ServiceApiSiteForbiddenError()

            return ServiceApiSite(
                title=site.title,
                chat_color_theme=site.chat_color_theme,
                chat_color_theme_inverted=site.chat_color_theme_inverted,
                icon_type=str(site.icon_type) if site.icon_type is not None else None,
                icon=site.icon,
                icon_background=site.icon_background,
                description=site.description,
                copyright=site.copyright,
                privacy_policy=site.privacy_policy,
                input_placeholder=site.input_placeholder,
                custom_disclaimer=site.custom_disclaimer,
                default_language=site.default_language,
                show_workflow_steps=site.show_workflow_steps,
                use_icon_as_answer_icon=site.use_icon_as_answer_icon,
            )
