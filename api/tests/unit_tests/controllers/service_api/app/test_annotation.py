from datetime import UTC, datetime
from inspect import unwrap
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from flask import Flask
from pydantic import ValidationError
from werkzeug.exceptions import NotFound

from controllers.service_api.app.annotation import (
    AnnotationCreatePayload,
    AnnotationListApi,
    AnnotationReplyActionApi,
    AnnotationReplyActionPayload,
    AnnotationUpdateDeleteApi,
)
from machinery.context import ServiceApiRequestContext
from services.service_api_annotation_service import (
    ServiceApiAnnotation,
    ServiceApiAnnotationNotFoundError,
    ServiceApiAnnotationPage,
)


@pytest.fixture
def flask_app() -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = True
    return app


def _context() -> ServiceApiRequestContext:
    return ServiceApiRequestContext(tenant_id="tenant-1", app_id="app-1")


def _annotation() -> ServiceApiAnnotation:
    return ServiceApiAnnotation(
        id="annotation-1",
        question="question",
        content="answer",
        hit_count=0,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _install(annotations: MagicMock):
    return patch(
        "controllers.service_api.app.annotation.application_services",
        return_value=SimpleNamespace(service_api_annotations=annotations),
    )


def test_payload_contracts_reject_missing_required_fields() -> None:
    with pytest.raises(ValidationError):
        AnnotationCreatePayload.model_validate({"question": "q"})
    with pytest.raises(ValidationError):
        AnnotationReplyActionPayload.model_validate({"score_threshold": 0.8})


def test_configure_reply_parses_payload_and_calls_application_service(flask_app: Flask) -> None:
    annotations = MagicMock()
    annotations.configure_reply.return_value = {"job_id": "job-1", "job_status": "waiting"}
    payload = {
        "score_threshold": 0.8,
        "embedding_provider_name": "provider",
        "embedding_model_name": "model",
    }

    with (
        flask_app.test_request_context("/", method="POST", json=payload),
        patch("controllers.service_api.app.annotation.service_api_ns") as namespace,
        _install(annotations),
    ):
        namespace.payload = payload
        response, status = unwrap(AnnotationReplyActionApi.post)(
            AnnotationReplyActionApi(),
            _context(),
            "enable",
        )

    assert status == 200
    assert response["job_id"] == "job-1"
    annotations.configure_reply.assert_called_once_with(
        _context(),
        action="enable",
        score_threshold=0.8,
        embedding_provider_name="provider",
        embedding_model_name="model",
    )


def test_list_annotations_parses_query_and_serializes_contract(flask_app: Flask) -> None:
    annotations = MagicMock()
    annotations.list.return_value = ServiceApiAnnotationPage(items=(_annotation(),), total=1)

    with flask_app.test_request_context("/?page=2&limit=10&keyword=hello"), _install(annotations):
        response = unwrap(AnnotationListApi.get)(AnnotationListApi(), _context())

    assert response["total"] == 1
    assert response["page"] == 2
    assert response["data"][0]["id"] == "annotation-1"
    annotations.list.assert_called_once_with(_context(), page=2, limit=10, keyword="hello")


def test_create_update_and_delete_delegate_to_one_application_service(flask_app: Flask) -> None:
    annotations = MagicMock()
    annotations.create.return_value = _annotation()
    annotations.update.return_value = _annotation()
    annotation_id = uuid4()
    payload = {"question": "question", "answer": "answer"}

    with (
        flask_app.test_request_context("/", method="POST", json=payload),
        patch("controllers.service_api.app.annotation.service_api_ns") as namespace,
        _install(annotations),
    ):
        namespace.payload = payload
        created, created_status = unwrap(AnnotationListApi.post)(AnnotationListApi(), _context())
        updated = unwrap(AnnotationUpdateDeleteApi.put)(
            AnnotationUpdateDeleteApi(),
            _context(),
            annotation_id,
        )
        deleted = unwrap(AnnotationUpdateDeleteApi.delete)(
            AnnotationUpdateDeleteApi(),
            _context(),
            annotation_id,
        )

    assert created_status == 201
    assert created["id"] == "annotation-1"
    assert updated["id"] == "annotation-1"
    assert deleted == ("", 204)
    annotations.create.assert_called_once_with(_context(), question="question", answer="answer")
    annotations.update.assert_called_once_with(
        _context(),
        annotation_id=str(annotation_id),
        question="question",
        answer="answer",
    )
    annotations.delete.assert_called_once_with(_context(), annotation_id=str(annotation_id))


def test_update_maps_application_not_found(flask_app: Flask) -> None:
    annotations = MagicMock()
    annotations.update.side_effect = ServiceApiAnnotationNotFoundError()
    payload = {"question": "question", "answer": "answer"}

    with (
        flask_app.test_request_context("/", method="PUT", json=payload),
        patch("controllers.service_api.app.annotation.service_api_ns") as namespace,
        _install(annotations),
    ):
        namespace.payload = payload
        with pytest.raises(NotFound):
            unwrap(AnnotationUpdateDeleteApi.put)(
                AnnotationUpdateDeleteApi(),
                _context(),
                uuid4(),
            )
