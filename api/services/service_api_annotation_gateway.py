"""Infrastructure adapter for Service API annotation use cases."""

import uuid
from typing import override

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session, sessionmaker

from extensions.ext_redis import RedisClientWrapper
from libs.helper import escape_like_pattern
from libs.pagination import paginate_query
from machinery.context import ServiceApiRequestContext
from models import Account, TenantAccountJoin
from models.account import TenantAccountRole
from models.model import AppAnnotationHitHistory, AppAnnotationSetting, MessageAnnotation
from services.service_api_annotation_service import (
    ServiceApiAnnotation,
    ServiceApiAnnotationGateway,
    ServiceApiAnnotationJob,
    ServiceApiAnnotationNotFoundError,
    ServiceApiAnnotationPage,
)
from tasks.annotation.add_annotation_to_index_task import add_annotation_to_index_task
from tasks.annotation.delete_annotation_index_task import delete_annotation_index_task
from tasks.annotation.disable_annotation_reply_task import disable_annotation_reply_task
from tasks.annotation.enable_annotation_reply_task import enable_annotation_reply_task
from tasks.annotation.update_annotation_to_index_task import update_annotation_to_index_task


class SqlAlchemyServiceApiAnnotationGateway(ServiceApiAnnotationGateway):
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        redis: RedisClientWrapper,
    ) -> None:
        self._session_factory = session_factory
        self._redis = redis

    @staticmethod
    def _record(annotation: MessageAnnotation) -> ServiceApiAnnotation:
        return ServiceApiAnnotation(
            id=annotation.id,
            question=annotation.question,
            content=annotation.content,
            hit_count=annotation.hit_count,
            created_at=annotation.created_at,
        )

    def _owner_account_id(self, context: ServiceApiRequestContext) -> str:
        with self._session_factory() as session:
            account_id = session.scalar(
                select(Account.id)
                .join(TenantAccountJoin, TenantAccountJoin.account_id == Account.id)
                .where(
                    TenantAccountJoin.tenant_id == context.tenant_id,
                    TenantAccountJoin.role == TenantAccountRole.OWNER,
                )
            )
        if account_id is None:
            raise RuntimeError("Admitted tenant owner no longer exists")
        return account_id

    @override
    def configure_reply(
        self,
        context: ServiceApiRequestContext,
        *,
        action: str,
        score_threshold: float,
        embedding_provider_name: str,
        embedding_model_name: str,
    ) -> ServiceApiAnnotationJob:
        operation_key = f"{action}_app_annotation_{context.app_id}"
        cached_job_id = self._redis.get(operation_key)
        if cached_job_id is not None:
            job_id = cached_job_id.decode() if isinstance(cached_job_id, bytes) else str(cached_job_id)
            return ServiceApiAnnotationJob(job_id=job_id, job_status="processing")

        job_id = str(uuid.uuid4())
        self._redis.setnx(f"{action}_app_annotation_job_{job_id}", "waiting")
        if action == "enable":
            enable_annotation_reply_task.delay(
                job_id,
                context.app_id,
                self._owner_account_id(context),
                context.tenant_id,
                score_threshold,
                embedding_provider_name,
                embedding_model_name,
            )
        else:
            disable_annotation_reply_task.delay(job_id, context.app_id, context.tenant_id)
        return ServiceApiAnnotationJob(job_id=job_id, job_status="waiting")

    @override
    def get_job(
        self,
        context: ServiceApiRequestContext,
        *,
        action: str,
        job_id: str,
    ) -> ServiceApiAnnotationJob:
        del context
        cached_status = self._redis.get(f"{action}_app_annotation_job_{job_id}")
        if cached_status is None:
            raise ServiceApiAnnotationNotFoundError()
        job_status = cached_status.decode() if isinstance(cached_status, bytes) else str(cached_status)
        error_msg = ""
        if job_status == "error":
            cached_error = self._redis.get(f"{action}_app_annotation_error_{job_id}")
            if cached_error is not None:
                error_msg = cached_error.decode() if isinstance(cached_error, bytes) else str(cached_error)
        return ServiceApiAnnotationJob(job_id=job_id, job_status=job_status, error_msg=error_msg)

    @override
    def list(
        self,
        context: ServiceApiRequestContext,
        *,
        page: int,
        limit: int,
        keyword: str,
    ) -> ServiceApiAnnotationPage:
        stmt = select(MessageAnnotation).where(MessageAnnotation.app_id == context.app_id)
        if keyword:
            escaped_keyword = escape_like_pattern(keyword)
            stmt = stmt.where(
                or_(
                    MessageAnnotation.question.ilike(f"%{escaped_keyword}%", escape="\\"),
                    MessageAnnotation.content.ilike(f"%{escaped_keyword}%", escape="\\"),
                )
            )
        stmt = stmt.order_by(MessageAnnotation.created_at.desc(), MessageAnnotation.id.desc())
        with self._session_factory() as session:
            annotations = paginate_query(stmt, session=session, page=page, per_page=limit, max_per_page=100)
            return ServiceApiAnnotationPage(
                items=tuple(self._record(annotation) for annotation in annotations.items),
                total=annotations.total or 0,
            )

    @override
    def create(
        self,
        context: ServiceApiRequestContext,
        *,
        question: str,
        answer: str,
    ) -> ServiceApiAnnotation:
        owner_account_id = self._owner_account_id(context)
        setting = None
        with self._session_factory.begin() as session:
            annotation = MessageAnnotation(
                app_id=context.app_id,
                content=answer,
                question=question,
                account_id=owner_account_id,
            )
            session.add(annotation)
            session.flush()
            session.refresh(annotation)
            setting = session.scalar(select(AppAnnotationSetting).where(AppAnnotationSetting.app_id == context.app_id))
            record = self._record(annotation)

        if setting is not None:
            add_annotation_to_index_task.delay(
                record.id,
                question,
                context.tenant_id,
                context.app_id,
                setting.collection_binding_id,
            )
        return record

    @override
    def update(
        self,
        context: ServiceApiRequestContext,
        *,
        annotation_id: str,
        question: str,
        answer: str,
    ) -> ServiceApiAnnotation:
        setting = None
        with self._session_factory.begin() as session:
            annotation = session.scalar(
                select(MessageAnnotation).where(
                    MessageAnnotation.id == annotation_id,
                    MessageAnnotation.app_id == context.app_id,
                )
            )
            if annotation is None:
                raise ServiceApiAnnotationNotFoundError()
            annotation.question = question
            annotation.content = answer
            session.flush()
            setting = session.scalar(select(AppAnnotationSetting).where(AppAnnotationSetting.app_id == context.app_id))
            record = self._record(annotation)

        if setting is not None:
            update_annotation_to_index_task.delay(
                record.id,
                record.question,
                context.tenant_id,
                context.app_id,
                setting.collection_binding_id,
            )
        return record

    @override
    def delete(self, context: ServiceApiRequestContext, *, annotation_id: str) -> None:
        setting = None
        with self._session_factory.begin() as session:
            annotation = session.scalar(
                select(MessageAnnotation).where(
                    MessageAnnotation.id == annotation_id,
                    MessageAnnotation.app_id == context.app_id,
                )
            )
            if annotation is None:
                raise ServiceApiAnnotationNotFoundError()
            session.execute(
                delete(AppAnnotationHitHistory).where(
                    AppAnnotationHitHistory.app_id == context.app_id,
                    AppAnnotationHitHistory.annotation_id == annotation_id,
                )
            )
            setting = session.scalar(select(AppAnnotationSetting).where(AppAnnotationSetting.app_id == context.app_id))
            session.delete(annotation)

        if setting is not None:
            delete_annotation_index_task.delay(
                annotation_id,
                context.app_id,
                context.tenant_id,
                setting.collection_binding_id,
            )
