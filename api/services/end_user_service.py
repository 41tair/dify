from collections.abc import Mapping

from core.db.session_factory import get_session_maker
from models.enums import EndUserType
from models.model import App, EndUser
from repositories.end_user_repository import EndUserRepository


class EndUserService:
    """Compatibility facade for existing non-application-service callers.

    New application services inject their repository. Existing webhook,
    OpenAPI, plugin and trigger entry points share the same concurrency-safe
    implementation through this facade while they are migrated independently.
    """

    @staticmethod
    def _repository() -> EndUserRepository:
        return EndUserRepository(session_factory=get_session_maker())

    @classmethod
    def get_end_user_by_id(cls, *, tenant_id: str, app_id: str, end_user_id: str) -> EndUser | None:
        return cls._repository().get_by_id(
            tenant_id=tenant_id,
            app_id=app_id,
            end_user_id=end_user_id,
        )

    @classmethod
    def get_or_create_end_user(cls, app_model: App, user_id: str | None = None) -> EndUser:
        return cls.get_or_create_end_user_by_type(
            EndUserType.SERVICE_API,
            app_model.tenant_id,
            app_model.id,
            user_id,
        )

    @classmethod
    def get_or_create_end_user_by_type(
        cls,
        type: EndUserType,
        tenant_id: str,
        app_id: str,
        user_id: str | None = None,
    ) -> EndUser:
        return cls._repository().get_or_create(
            end_user_type=type,
            tenant_id=tenant_id,
            app_id=app_id,
            user_id=user_id,
        )

    @classmethod
    def create_end_user_batch(
        cls,
        type: EndUserType,
        tenant_id: str,
        app_ids: list[str],
        user_id: str,
    ) -> Mapping[str, EndUser]:
        return cls._repository().get_or_create_batch(
            end_user_type=type,
            tenant_id=tenant_id,
            app_ids=app_ids,
            user_id=user_id,
        )
