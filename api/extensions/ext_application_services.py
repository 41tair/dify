"""Composition root for application services used by transport adapters."""

from dataclasses import dataclass
from typing import cast

from flask import Flask, current_app
from sqlalchemy.orm import Session, sessionmaker

from configs import dify_config
from constants.dsl_version import CURRENT_APP_DSL_VERSION
from core.db.session_factory import get_session_maker
from core.schemas.schema_manager import SchemaManager
from enums import DeploymentEdition
from extensions.ext_redis import RedisClientWrapper, redis_client
from repositories.app_definition_query_repository import AppDefinitionQueryRepository
from repositories.end_user_query_repository import EndUserQueryRepository
from repositories.explore_banner_query_repository import ExploreBannerQueryRepository
from repositories.installation_state_repository import InstallationStateRepository
from repositories.service_api_admission_repository import SqlAlchemyServiceApiAdmissionRepository
from repositories.workspace_member_query_repository import WorkspaceMemberQueryRepository
from repositories.workspace_query_repository import WorkspaceQueryRepository
from services.app_definition_query_service import AppDefinitionQueryService
from services.end_user_query_service import EndUserQueryService
from services.explore_banner_query_service import ExploreBannerQueryService
from services.feature_query_service import FeatureQueryService
from services.feature_service import FeatureService
from services.feature_service_gateway import FeatureServiceGateway
from services.init_validation_service import InitValidationService
from services.schema_definition_service import SchemaDefinitionService
from services.service_api_admission_service import ServiceApiAdmissionService
from services.service_api_annotation_gateway import SqlAlchemyServiceApiAnnotationGateway
from services.service_api_annotation_service import ServiceApiAnnotationService
from services.service_api_conversation_gateway import SqlAlchemyServiceApiConversationGateway
from services.service_api_conversation_service import ServiceApiConversationService
from services.service_api_file_gateway import SqlAlchemyServiceApiFileGateway
from services.service_api_file_service import ServiceApiFileService
from services.service_api_generation_gateway import DefaultServiceApiGenerationGateway
from services.service_api_generation_service import ServiceApiGenerationService
from services.service_api_human_input_gateway import DefaultServiceApiHumanInputGateway
from services.service_api_human_input_service import ServiceApiHumanInputService
from services.service_api_site_gateway import SqlAlchemyServiceApiSiteGateway
from services.service_api_site_service import ServiceApiSiteService
from services.service_api_token_gateway import CachedServiceApiTokenGateway
from services.service_api_workflow_gateway import DefaultServiceApiWorkflowGateway
from services.service_api_workflow_service import ServiceApiWorkflowService
from services.service_api_workflow_version_gateway import DeploymentServiceApiWorkflowVersionPolicy
from services.setup_adapters import RedisSetupLock, RegisterServiceAccountProvisioner
from services.setup_service import SetupService
from services.workspace_member_query_service import WorkspaceMemberQueryService
from services.workspace_member_role_resolver import DeploymentWorkspaceMemberRoleResolver
from services.workspace_plan_gateway import DeploymentWorkspacePlanGateway
from services.workspace_query_service import WorkspaceQueryService

_EXTENSION_KEY = "application_services"


@dataclass(frozen=True, slots=True)
class ApplicationServices:
    app_definitions: AppDefinitionQueryService
    end_user_queries: EndUserQueryService
    service_api_admission: ServiceApiAdmissionService
    service_api_annotations: ServiceApiAnnotationService
    service_api_files: ServiceApiFileService
    service_api_human_inputs: ServiceApiHumanInputService
    service_api_conversations: ServiceApiConversationService
    service_api_generation: ServiceApiGenerationService
    service_api_sites: ServiceApiSiteService
    service_api_workflows: ServiceApiWorkflowService
    explore_banner_queries: ExploreBannerQueryService
    schema_definitions: SchemaDefinitionService
    setup: SetupService
    feature_queries: FeatureQueryService
    init_validation: InitValidationService
    workspace_queries: WorkspaceQueryService
    workspace_member_queries: WorkspaceMemberQueryService


def build_application_services(
    *,
    database_client: sessionmaker[Session],
    deployment_edition: DeploymentEdition,
    initialization_password: str,
    redis: RedisClientWrapper,
) -> ApplicationServices:
    installation_state = InstallationStateRepository(client=database_client)
    service_api_workflow_versions = DeploymentServiceApiWorkflowVersionPolicy(
        deployment_edition=deployment_edition,
    )
    return ApplicationServices(
        app_definitions=AppDefinitionQueryService(
            definitions=AppDefinitionQueryRepository(session_factory=database_client),
            builtin_icon_url_prefix=(
                dify_config.CONSOLE_API_URL + "/console/api/workspaces/current/tool-provider/builtin/"
            ),
        ),
        end_user_queries=EndUserQueryService(
            end_users=EndUserQueryRepository(session_factory=database_client),
        ),
        service_api_admission=ServiceApiAdmissionService(
            tokens=CachedServiceApiTokenGateway(),
            admissions=SqlAlchemyServiceApiAdmissionRepository(session_factory=database_client),
        ),
        service_api_annotations=ServiceApiAnnotationService(
            annotations=SqlAlchemyServiceApiAnnotationGateway(
                session_factory=database_client,
                redis=redis,
            ),
        ),
        service_api_files=ServiceApiFileService(
            files=SqlAlchemyServiceApiFileGateway(session_factory=database_client),
        ),
        service_api_human_inputs=ServiceApiHumanInputService(
            forms=DefaultServiceApiHumanInputGateway(session_factory=database_client),
        ),
        service_api_conversations=ServiceApiConversationService(
            conversations=SqlAlchemyServiceApiConversationGateway(session_factory=database_client),
        ),
        service_api_generation=ServiceApiGenerationService(
            generation=DefaultServiceApiGenerationGateway(session_factory=database_client),
            workflow_versions=service_api_workflow_versions,
        ),
        service_api_sites=ServiceApiSiteService(
            sites=SqlAlchemyServiceApiSiteGateway(session_factory=database_client),
        ),
        service_api_workflows=ServiceApiWorkflowService(
            workflows=DefaultServiceApiWorkflowGateway(
                session_factory=database_client,
                redis=redis,
            ),
            workflow_versions=service_api_workflow_versions,
        ),
        explore_banner_queries=ExploreBannerQueryService(
            banners=ExploreBannerQueryRepository(client=database_client),
            is_enabled=FeatureService.is_explore_banner_enabled,
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
        init_validation=InitValidationService(
            state=installation_state,
            validation_required=(deployment_edition != DeploymentEdition.CLOUD and bool(initialization_password)),
            expected_password=initialization_password,
        ),
        workspace_queries=WorkspaceQueryService(
            workspaces=WorkspaceQueryRepository(
                client=database_client,
            ),
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
        initialization_password=dify_config.INIT_PASSWORD,
        redis=redis_client,
    )


def application_services() -> ApplicationServices:
    """Return the application services bound to the current Flask app."""
    return cast(ApplicationServices, current_app.extensions[_EXTENSION_KEY])
