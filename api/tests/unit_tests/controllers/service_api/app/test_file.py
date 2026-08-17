from datetime import UTC, datetime
from inspect import unwrap
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from controllers.common.errors import NoFileUploadedError, TooManyFilesError
from controllers.service_api.app.file import FileApi
from machinery.context import ServiceApiEndUserIdentity, ServiceApiRequestContext
from services.service_api_file_service import ServiceApiUploadedFile


@pytest.fixture
def flask_app() -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = True
    return app


def _context() -> ServiceApiRequestContext:
    return ServiceApiRequestContext(
        tenant_id="tenant-1",
        app_id="app-1",
        end_user=ServiceApiEndUserIdentity(id="end-user-1", external_user_id="external-1"),
    )


def _upload_result() -> ServiceApiUploadedFile:
    return ServiceApiUploadedFile(
        id="file-1",
        name="sample.txt",
        size=7,
        extension="txt",
        mime_type="text/plain",
        created_by="end-user-1",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        source_url="/files/file-1",
        tenant_id="tenant-1",
    )


def test_upload_converts_filestorage_to_plain_application_input(flask_app: Flask) -> None:
    files = MagicMock()
    files.upload.return_value = _upload_result()

    with (
        flask_app.test_request_context(
            "/",
            method="POST",
            data={"file": (BytesIO(b"content"), "sample.txt")},
            content_type="multipart/form-data",
        ),
        patch(
            "controllers.service_api.app.file.application_services",
            return_value=SimpleNamespace(service_api_files=files),
        ),
    ):
        response, status = unwrap(FileApi.post)(FileApi(), _context())

    assert status == 201
    assert response["id"] == "file-1"
    files.upload.assert_called_once_with(
        _context(),
        filename="sample.txt",
        content=b"content",
        mimetype="text/plain",
    )


def test_upload_rejects_missing_file_before_application_call(flask_app: Flask) -> None:
    files = MagicMock()
    with (
        flask_app.test_request_context("/", method="POST"),
        patch(
            "controllers.service_api.app.file.application_services",
            return_value=SimpleNamespace(service_api_files=files),
        ),
        pytest.raises(NoFileUploadedError),
    ):
        unwrap(FileApi.post)(FileApi(), _context())

    files.upload.assert_not_called()


def test_upload_rejects_multiple_files_before_application_call(flask_app: Flask) -> None:
    files = MagicMock()
    with (
        flask_app.test_request_context(
            "/",
            method="POST",
            data={
                "file": (BytesIO(b"one"), "one.txt"),
                "other": (BytesIO(b"two"), "two.txt"),
            },
            content_type="multipart/form-data",
        ),
        patch(
            "controllers.service_api.app.file.application_services",
            return_value=SimpleNamespace(service_api_files=files),
        ),
        pytest.raises(TooManyFilesError),
    ):
        unwrap(FileApi.post)(FileApi(), _context())

    files.upload.assert_not_called()
