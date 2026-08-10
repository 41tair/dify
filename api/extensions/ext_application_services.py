"""Composition root for application services used by transport adapters."""

from dataclasses import dataclass
from typing import cast

from flask import Flask, current_app
from sqlalchemy.orm import Session, sessionmaker

from configs import dify_config
from constants.dsl_version import CURRENT_APP_DSL_VERSION
from core.db.session_factory import get_session_maker
from core.schemas.schema_manager import SchemaManager
from enums.deployment_edition import DeploymentEdition
from extensions.ext_redis import RedisClientWrapper, redis_client
from libs.datetime_utils import naive_utc_now
from libs.helper import RateLimiter
from repositories.account_unit_of_work import SQLAlchemyAccountUnitOfWorkFactory
from repositories.installation_state_repository import InstallationStateRepository
from repositories.workspace_member_query_repository import WorkspaceMemberQueryRepository
from repositories.workspace_query_repository import WorkspaceQueryRepository
from services.account_avatar_file_gateway import SQLAlchemyAccountAvatarFileGateway
from services.account_avatar_service import AccountAvatarService
from services.account_deletion_adapters import (
    CeleryAccountDeletionScheduler,
    CeleryAccountDeletionVerificationNotifier,
    EnterpriseAccountDeletionSyncGateway,
    TokenManagerAccountDeletionVerificationGateway,
)
from services.account_deletion_service import AccountDeletionService
from services.account_initialization_service import AccountInitializationService
from services.account_integration_service import AccountIntegrationService
from services.account_password_hasher import LegacyAccountPasswordHasher
from services.account_password_service import AccountPasswordService
from services.account_profile_service import AccountProfileService
from services.feature_query_service import FeatureQueryService
from services.feature_service import FeatureService
from services.feature_service_gateway import FeatureServiceGateway
from services.schema_definition_service import SchemaDefinitionService
from services.setup_adapters import RedisSetupLock, RegisterServiceAccountProvisioner
from services.setup_service import SetupService
from services.workspace_member_query_service import WorkspaceMemberQueryService
from services.workspace_member_role_resolver import DeploymentWorkspaceMemberRoleResolver
from services.workspace_plan_gateway import DeploymentWorkspacePlanGateway
from services.workspace_query_service import WorkspaceQueryService

_EXTENSION_KEY = "application_services"


@dataclass(frozen=True, slots=True)
class AccountApplicationServices:
    avatar: AccountAvatarService
    deletion: AccountDeletionService
    initialization: AccountInitializationService
    integrations: AccountIntegrationService
    password: AccountPasswordService
    profile: AccountProfileService


@dataclass(frozen=True, slots=True)
class ApplicationServices:
    accounts: AccountApplicationServices
    schema_definitions: SchemaDefinitionService
    setup: SetupService
    feature_queries: FeatureQueryService
    workspace_queries: WorkspaceQueryService
    workspace_member_queries: WorkspaceMemberQueryService


def build_application_services(
    *,
    database_client: sessionmaker[Session],
    deployment_edition: DeploymentEdition,
    redis: RedisClientWrapper,
) -> ApplicationServices:
    installation_state = InstallationStateRepository(client=database_client)
    account_unit_of_work = SQLAlchemyAccountUnitOfWorkFactory(database_client)
    workspace_query_repository = WorkspaceQueryRepository(client=database_client)
    return ApplicationServices(
        accounts=AccountApplicationServices(
            avatar=AccountAvatarService(
                files=SQLAlchemyAccountAvatarFileGateway(session_factory=database_client),
            ),
            deletion=AccountDeletionService(
                unit_of_work=account_unit_of_work,
                memberships=workspace_query_repository,
                verification=TokenManagerAccountDeletionVerificationGateway(),
                notifications=CeleryAccountDeletionVerificationNotifier(
                    rate_limiter=RateLimiter(
                        prefix="email_code_account_deletion_rate_limit",
                        max_attempts=1,
                        time_window=60,
                        redis_client=redis,
                    )
                ),
                synchronization=EnterpriseAccountDeletionSyncGateway(),
                scheduler=CeleryAccountDeletionScheduler(),
            ),
            initialization=AccountInitializationService(
                unit_of_work=account_unit_of_work,
                invitation_required=deployment_edition == DeploymentEdition.CLOUD,
                now=naive_utc_now,
            ),
            integrations=AccountIntegrationService(unit_of_work=account_unit_of_work),
            password=AccountPasswordService(
                unit_of_work=account_unit_of_work,
                passwords=LegacyAccountPasswordHasher(),
            ),
            profile=AccountProfileService(unit_of_work=account_unit_of_work),
        ),
        schema_definitions=SchemaDefinitionService(source_factory=SchemaManager),
        setup=SetupService(
            state=installation_state,
            accounts=RegisterServiceAccountProvisioner(client=database_client),
            lock=RedisSetupLock(client=redis),
            setup_required=deployment_edition != DeploymentEdition.CLOUD,
        ),
        feature_queries=FeatureQueryService(
            features=FeatureServiceGateway(),
            trial_models=FeatureService.get_trial_models(),
            app_dsl_version=CURRENT_APP_DSL_VERSION,
        ),
        workspace_queries=WorkspaceQueryService(
            workspaces=workspace_query_repository,
            plans=DeploymentWorkspacePlanGateway(),
        ),
        workspace_member_queries=WorkspaceMemberQueryService(
            members=WorkspaceMemberQueryRepository(
                session_factory=database_client,
            ),
            roles=DeploymentWorkspaceMemberRoleResolver(),
        ),
    )


def init_app(app: Flask) -> None:
    app.extensions[_EXTENSION_KEY] = build_application_services(
        database_client=get_session_maker(),
        deployment_edition=dify_config.DEPLOYMENT_EDITION,
        redis=redis_client,
    )


def application_services() -> ApplicationServices:
    """Return the application services bound to the current Flask app."""
    return cast(ApplicationServices, current_app.extensions[_EXTENSION_KEY])
