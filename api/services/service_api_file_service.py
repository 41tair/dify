"""Application services for Service API file and audio use cases."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from machinery.context import ServiceApiRequestContext


@dataclass(frozen=True, slots=True, kw_only=True)
class ServiceApiUploadedFile:
    id: str
    name: str
    size: int
    extension: str | None
    mime_type: str | None
    created_by: str | None
    created_at: datetime | None
    source_url: str | None
    tenant_id: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ServiceApiFilePreview:
    body: Iterable[bytes]
    mime_type: str | None
    size: int
    name: str
    extension: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ServiceApiAudioContent:
    body: Any
    mime_type: str | None = None


class ServiceApiReadStream(Protocol):
    def read(self, size: int = -1, /) -> bytes: ...


class ServiceApiFileNotFoundError(ValueError):
    pass


class ServiceApiFileAccessDeniedError(ValueError):
    pass


class ServiceApiFileGateway(Protocol):
    def upload(
        self,
        context: ServiceApiRequestContext,
        *,
        filename: str,
        content: bytes,
        mimetype: str,
    ) -> ServiceApiUploadedFile: ...

    def preview(self, context: ServiceApiRequestContext, *, file_id: str) -> ServiceApiFilePreview: ...

    def audio_to_text(
        self,
        context: ServiceApiRequestContext,
        *,
        filename: str | None,
        stream: ServiceApiReadStream | None,
        mimetype: str | None,
    ) -> dict[str, str]: ...

    def text_to_audio(
        self,
        context: ServiceApiRequestContext,
        *,
        text: str | None,
        voice: str | None,
        message_id: str | None,
    ) -> ServiceApiAudioContent: ...


class ServiceApiFileService:
    def __init__(self, *, files: ServiceApiFileGateway) -> None:
        self._files = files

    def upload(
        self,
        context: ServiceApiRequestContext,
        *,
        filename: str,
        content: bytes,
        mimetype: str,
    ) -> ServiceApiUploadedFile:
        return self._files.upload(context, filename=filename, content=content, mimetype=mimetype)

    def preview(self, context: ServiceApiRequestContext, *, file_id: str) -> ServiceApiFilePreview:
        return self._files.preview(context, file_id=file_id)

    def audio_to_text(
        self,
        context: ServiceApiRequestContext,
        *,
        filename: str | None,
        stream: ServiceApiReadStream | None,
        mimetype: str | None,
    ) -> dict[str, str]:
        return self._files.audio_to_text(
            context,
            filename=filename,
            stream=stream,
            mimetype=mimetype,
        )

    def text_to_audio(
        self,
        context: ServiceApiRequestContext,
        *,
        text: str | None,
        voice: str | None,
        message_id: str | None,
    ) -> ServiceApiAudioContent:
        return self._files.text_to_audio(
            context,
            text=text,
            voice=voice,
            message_id=message_id,
        )
