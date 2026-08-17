from inspect import unwrap
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from flask import Flask

from controllers.service_api.app.error import FileAccessDeniedError, FileNotFoundError
from controllers.service_api.app.file_preview import FilePreviewApi
from machinery.context import ServiceApiRequestContext
from services.service_api_file_service import (
    ServiceApiFileAccessDeniedError,
    ServiceApiFileNotFoundError,
    ServiceApiFilePreview,
)


@pytest.fixture
def flask_app() -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = True
    return app


def _context() -> ServiceApiRequestContext:
    return ServiceApiRequestContext(tenant_id="tenant-1", app_id="app-1")


@pytest.mark.parametrize(
    ("as_attachment", "mime_type", "name", "extension", "size"),
    [
        (False, "image/jpeg", "test_file.jpg", "jpg", 1024),
        (True, "image/jpeg", "test_file.jpg", "jpg", 1024),
        (False, "text/html", "unsafe.html", "html", 1024),
        (False, "video/mp4", "test_file.mp4", "mp4", 1024),
        (False, "image/jpeg", "test_file.jpg", "jpg", 0),
    ],
)
def test_build_file_response_remains_a_transport_concern(
    as_attachment: bool,
    mime_type: str,
    name: str,
    extension: str,
    size: int,
) -> None:
    preview = ServiceApiFilePreview(
        body=[b"content"],
        mime_type=mime_type,
        size=size,
        name=name,
        extension=extension,
    )

    response = FilePreviewApi()._build_file_response(preview, as_attachment)

    assert response.direct_passthrough is True
    assert "Cache-Control" in response.headers
    assert ("Content-Length" in response.headers) is bool(size)
    if as_attachment or mime_type == "text/html":
        assert "attachment" in response.headers["Content-Disposition"]
        assert response.headers["Content-Type"] == "application/octet-stream"
    else:
        assert response.mimetype == mime_type
    if mime_type == "text/html":
        assert response.headers["X-Content-Type-Options"] == "nosniff"
    if mime_type.startswith("video/"):
        assert response.headers["Accept-Ranges"] == "bytes"


def test_get_delegates_ownership_and_storage_to_application_service(flask_app: Flask) -> None:
    file_id = uuid4()
    preview = ServiceApiFilePreview(
        body=[b"content"],
        mime_type="image/jpeg",
        size=7,
        name="image.jpg",
        extension="jpg",
    )
    files = MagicMock()
    files.preview.return_value = preview

    with (
        flask_app.test_request_context("/?as_attachment=true"),
        patch(
            "controllers.service_api.app.file_preview.application_services",
            return_value=SimpleNamespace(service_api_files=files),
        ),
    ):
        response = unwrap(FilePreviewApi.get)(FilePreviewApi(), _context(), file_id)

    files.preview.assert_called_once_with(_context(), file_id=str(file_id))
    assert response.headers["Content-Disposition"].startswith("attachment")


@pytest.mark.parametrize(
    ("service_error", "controller_error"),
    [
        (ServiceApiFileNotFoundError(), FileNotFoundError),
        (ServiceApiFileAccessDeniedError(), FileAccessDeniedError),
    ],
)
def test_get_maps_file_application_errors(
    flask_app: Flask,
    service_error: ValueError,
    controller_error: type[Exception],
) -> None:
    files = MagicMock()
    files.preview.side_effect = service_error

    with (
        flask_app.test_request_context("/"),
        patch(
            "controllers.service_api.app.file_preview.application_services",
            return_value=SimpleNamespace(service_api_files=files),
        ),
        pytest.raises(controller_error),
    ):
        unwrap(FilePreviewApi.get)(FilePreviewApi(), _context(), uuid4())
