from inspect import unwrap
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask, request

from controllers.service_api.app.audio import AudioApi, TextApi
from machinery.context import ServiceApiEndUserIdentity, ServiceApiRequestContext
from services.service_api_file_service import ServiceApiAudioContent


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


def _install(files: MagicMock):
    return patch(
        "controllers.service_api.app.audio.application_services",
        return_value=SimpleNamespace(service_api_files=files),
    )


def test_audio_to_text_passes_binary_stream_without_materializing_it(flask_app: Flask) -> None:
    files = MagicMock()
    files.audio_to_text.return_value = {"text": "hello"}

    with (
        flask_app.test_request_context(
            "/",
            method="POST",
            data={"file": (BytesIO(b"audio"), "sample.mp3")},
            content_type="multipart/form-data",
        ),
        _install(files),
    ):
        uploaded_stream = request.files["file"].stream
        response = unwrap(AudioApi.post)(AudioApi(), _context())
        assert response == {"text": "hello"}
        call = files.audio_to_text.call_args
        assert call.args == (_context(),)
        assert call.kwargs["filename"] == "sample.mp3"
        assert call.kwargs["stream"] is uploaded_stream
        assert call.kwargs["mimetype"] == "audio/mpeg"


def test_text_to_audio_builds_flask_response_only_in_controller(flask_app: Flask) -> None:
    files = MagicMock()
    files.text_to_audio.return_value = ServiceApiAudioContent(
        body=[b"audio"],
        mime_type="audio/mpeg",
    )
    payload = {"text": "hello", "voice": "voice-1"}

    with (
        flask_app.test_request_context("/", method="POST", json=payload),
        patch("controllers.service_api.app.audio.service_api_ns") as namespace,
        _install(files),
    ):
        namespace.payload = payload
        response = unwrap(TextApi.post)(TextApi(), _context())

    assert response.content_type == "audio/mpeg"
    assert response.direct_passthrough is True
    files.text_to_audio.assert_called_once_with(
        _context(),
        text="hello",
        voice="voice-1",
        message_id=None,
    )


def test_text_to_audio_returns_provider_value_without_http_metadata(flask_app: Flask) -> None:
    files = MagicMock()
    files.text_to_audio.return_value = ServiceApiAudioContent(body=b"audio")
    payload = {"text": "hello"}

    with (
        flask_app.test_request_context("/", method="POST", json=payload),
        patch("controllers.service_api.app.audio.service_api_ns") as namespace,
        _install(files),
    ):
        namespace.payload = payload
        response = unwrap(TextApi.post)(TextApi(), _context())

    assert response == b"audio"
