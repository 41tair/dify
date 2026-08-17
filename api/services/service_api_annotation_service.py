"""Application service for Service API annotation use cases."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from machinery.context import ServiceApiRequestContext


@dataclass(frozen=True, slots=True, kw_only=True)
class ServiceApiAnnotation:
    id: str
    question: str
    content: str
    hit_count: int
    created_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class ServiceApiAnnotationPage:
    items: tuple[ServiceApiAnnotation, ...]
    total: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ServiceApiAnnotationJob:
    job_id: str
    job_status: str
    error_msg: str = ""


class ServiceApiAnnotationNotFoundError(ValueError):
    pass


class ServiceApiAnnotationGateway(Protocol):
    def configure_reply(
        self,
        context: ServiceApiRequestContext,
        *,
        action: str,
        score_threshold: float,
        embedding_provider_name: str,
        embedding_model_name: str,
    ) -> ServiceApiAnnotationJob: ...

    def get_job(self, context: ServiceApiRequestContext, *, action: str, job_id: str) -> ServiceApiAnnotationJob: ...

    def list(
        self,
        context: ServiceApiRequestContext,
        *,
        page: int,
        limit: int,
        keyword: str,
    ) -> ServiceApiAnnotationPage: ...

    def create(
        self,
        context: ServiceApiRequestContext,
        *,
        question: str,
        answer: str,
    ) -> ServiceApiAnnotation: ...

    def update(
        self,
        context: ServiceApiRequestContext,
        *,
        annotation_id: str,
        question: str,
        answer: str,
    ) -> ServiceApiAnnotation: ...

    def delete(self, context: ServiceApiRequestContext, *, annotation_id: str) -> None: ...


class ServiceApiAnnotationService:
    def __init__(self, *, annotations: ServiceApiAnnotationGateway) -> None:
        self._annotations = annotations

    def configure_reply(
        self,
        context: ServiceApiRequestContext,
        *,
        action: str,
        score_threshold: float,
        embedding_provider_name: str,
        embedding_model_name: str,
    ) -> ServiceApiAnnotationJob:
        return self._annotations.configure_reply(
            context,
            action=action,
            score_threshold=score_threshold,
            embedding_provider_name=embedding_provider_name,
            embedding_model_name=embedding_model_name,
        )

    def get_job(self, context: ServiceApiRequestContext, *, action: str, job_id: str) -> ServiceApiAnnotationJob:
        return self._annotations.get_job(context, action=action, job_id=job_id)

    def list(
        self,
        context: ServiceApiRequestContext,
        *,
        page: int,
        limit: int,
        keyword: str,
    ) -> ServiceApiAnnotationPage:
        return self._annotations.list(context, page=page, limit=limit, keyword=keyword)

    def create(
        self,
        context: ServiceApiRequestContext,
        *,
        question: str,
        answer: str,
    ) -> ServiceApiAnnotation:
        return self._annotations.create(context, question=question, answer=answer)

    def update(
        self,
        context: ServiceApiRequestContext,
        *,
        annotation_id: str,
        question: str,
        answer: str,
    ) -> ServiceApiAnnotation:
        return self._annotations.update(
            context,
            annotation_id=annotation_id,
            question=question,
            answer=answer,
        )

    def delete(self, context: ServiceApiRequestContext, *, annotation_id: str) -> None:
        self._annotations.delete(context, annotation_id=annotation_id)
