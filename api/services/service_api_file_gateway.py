"""Infrastructure adapter for Service API file and audio use cases."""

from collections.abc import Iterable
from typing import IO, Protocol, cast, override, runtime_checkable

from sqlalchemy import exists, select
from sqlalchemy.orm import Session, sessionmaker
from werkzeug.datastructures import FileStorage

from extensions.ext_storage import storage
from machinery.context import ServiceApiRequestContext
from models.model import App, EndUser, Message, MessageFile, UploadFile
from services.app_ref_service import AppRefService
from services.audio_service import AudioService
from services.file_service import FileService
from services.service_api_file_service import (
    ServiceApiAudioContent,
    ServiceApiFileAccessDeniedError,
    ServiceApiFileGateway,
    ServiceApiFileNotFoundError,
    ServiceApiFilePreview,
    ServiceApiReadStream,
    ServiceApiUploadedFile,
)


@runtime_checkable
class _StreamingResponse(Protocol):
    response: Iterable[bytes]
    content_type: str | None


class SqlAlchemyServiceApiFileGateway(ServiceApiFileGateway):
    def __init__(self, *, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    @staticmethod
    def _require_end_user(context: ServiceApiRequestContext):
        if context.end_user is None:
            raise RuntimeError("This Service API operation requires an EndUser")
        return context.end_user

    def _load_app(self, session: Session, context: ServiceApiRequestContext) -> App:
        app = session.scalar(
            select(App).where(
                App.id == context.app_id,
                App.tenant_id == context.tenant_id,
            )
        )
        if app is None:
            raise RuntimeError("Admitted app no longer exists")
        return app

    @override
    def upload(
        self,
        context: ServiceApiRequestContext,
        *,
        filename: str,
        content: bytes,
        mimetype: str,
    ) -> ServiceApiUploadedFile:
        identity = self._require_end_user(context)
        with self._session_factory() as session:
            end_user = session.get(EndUser, identity.id)
            if end_user is None:
                raise RuntimeError("Admitted EndUser no longer exists")
            session.expunge(end_user)

        upload_file = FileService(self._session_factory).upload_file(
            filename=filename,
            content=content,
            mimetype=mimetype,
            user=end_user,
        )
        return ServiceApiUploadedFile(
            id=upload_file.id,
            name=upload_file.name,
            size=upload_file.size,
            extension=upload_file.extension,
            mime_type=upload_file.mime_type,
            created_by=upload_file.created_by,
            created_at=upload_file.created_at,
            source_url=upload_file.source_url,
            tenant_id=upload_file.tenant_id,
        )

    @override
    def preview(self, context: ServiceApiRequestContext, *, file_id: str) -> ServiceApiFilePreview:
        with self._session_factory() as session:
            has_message_reference = exists(select(MessageFile.id).where(MessageFile.upload_file_id == UploadFile.id))
            has_app_message_reference = exists(
                select(MessageFile.id)
                .join(Message, Message.id == MessageFile.message_id)
                .where(
                    MessageFile.upload_file_id == UploadFile.id,
                    Message.app_id == context.app_id,
                )
            )
            row = session.execute(
                select(
                    UploadFile.tenant_id,
                    UploadFile.key,
                    UploadFile.mime_type,
                    UploadFile.size,
                    UploadFile.name,
                    UploadFile.extension,
                    has_message_reference.label("has_message_reference"),
                    has_app_message_reference.label("has_app_message_reference"),
                ).where(UploadFile.id == file_id)
            ).one_or_none()

        if row is None or row.key is None or not row.has_message_reference:
            raise ServiceApiFileNotFoundError()
        if row.tenant_id != context.tenant_id or not row.has_app_message_reference:
            raise ServiceApiFileAccessDeniedError()

        try:
            body = storage.load(row.key, stream=True)
        except Exception as error:
            raise ServiceApiFileNotFoundError() from error
        return ServiceApiFilePreview(
            body=body,
            mime_type=row.mime_type,
            size=row.size,
            name=row.name,
            extension=row.extension,
        )

    @override
    def audio_to_text(
        self,
        context: ServiceApiRequestContext,
        *,
        filename: str | None,
        stream: ServiceApiReadStream | None,
        mimetype: str | None,
    ) -> dict[str, str]:
        identity = self._require_end_user(context)
        file = None
        if stream is not None:
            file = FileStorage(
                stream=cast(IO[bytes], stream),
                filename=filename,
                content_type=mimetype,
            )
        with self._session_factory() as session:
            app = self._load_app(session, context)
            return AudioService.transcript_asr(
                app_model=app,
                file=file,
                session=session,
                end_user=identity.id,
            )

    @override
    def text_to_audio(
        self,
        context: ServiceApiRequestContext,
        *,
        text: str | None,
        voice: str | None,
        message_id: str | None,
    ) -> ServiceApiAudioContent:
        identity = self._require_end_user(context)
        with self._session_factory() as session:
            app = self._load_app(session, context)
            message_ref = None
            if message_id:
                app_ref = AppRefService.create_app_ref(app)
                message_ref = AppRefService.create_message_ref(
                    app_ref,
                    message_id,
                    end_user_id=identity.id,
                )
            result = AudioService.transcript_tts(
                app_model=app,
                session=session,
                text=text,
                voice=voice,
                end_user=identity.external_user_id,
                message_ref=message_ref,
            )

        if isinstance(result, _StreamingResponse):
            return ServiceApiAudioContent(
                body=result.response,
                mime_type=result.content_type,
            )
        return ServiceApiAudioContent(body=result)
