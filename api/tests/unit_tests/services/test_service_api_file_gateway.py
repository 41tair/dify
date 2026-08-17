from datetime import UTC, datetime
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker

from extensions.storage.storage_type import StorageType
from graphon.file import FileTransferMethod, FileType
from machinery.context import ServiceApiEndUserIdentity, ServiceApiRequestContext
from models.enums import ConversationFromSource, CreatorUserRole
from models.model import Message, MessageFile, UploadFile
from services.service_api_file_gateway import SqlAlchemyServiceApiFileGateway
from services.service_api_file_service import ServiceApiFileAccessDeniedError, ServiceApiFileNotFoundError


def _persist_preview(
    session: Session,
    *,
    app_id: str = "app-1",
    tenant_id: str = "tenant-1",
) -> UploadFile:
    upload = UploadFile(
        tenant_id=tenant_id,
        storage_type=StorageType.LOCAL,
        key="storage/key/file.jpg",
        name="file.jpg",
        size=7,
        extension="jpg",
        mime_type="image/jpeg",
        created_by_role=CreatorUserRole.END_USER,
        created_by="end-user-1",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        used=True,
    )
    message = Message(
        id=str(uuid4()),
        app_id=app_id,
        conversation_id=str(uuid4()),
        _inputs={},
        query="preview",
        message={},
        message_unit_price=Decimal(0),
        answer="answer",
        answer_unit_price=Decimal(0),
        currency="USD",
        from_source=ConversationFromSource.API,
    )
    message_file = MessageFile(
        message_id=message.id,
        type=FileType.IMAGE,
        transfer_method=FileTransferMethod.LOCAL_FILE,
        created_by_role=CreatorUserRole.END_USER,
        created_by="end-user-1",
        upload_file_id=upload.id,
    )
    session.add_all([message, message_file, upload])
    session.commit()
    return upload


def test_preview_returns_framework_neutral_content_after_scoped_lookup(
    sqlite_session: Session,
    sqlite_session_factory: sessionmaker[Session],
) -> None:
    upload = _persist_preview(sqlite_session)
    storage = SimpleNamespace(load=lambda _key, *, stream: [b"content"] if stream else b"content")
    gateway = SqlAlchemyServiceApiFileGateway(session_factory=sqlite_session_factory)

    with patch("services.service_api_file_gateway.storage", storage):
        preview = gateway.preview(
            ServiceApiRequestContext(tenant_id="tenant-1", app_id="app-1"),
            file_id=upload.id,
        )

    assert list(preview.body) == [b"content"]
    assert preview.mime_type == "image/jpeg"
    assert preview.name == "file.jpg"


def test_preview_accepts_an_upload_referenced_by_multiple_messages(
    sqlite_session: Session,
    sqlite_session_factory: sessionmaker[Session],
) -> None:
    upload = _persist_preview(sqlite_session)
    second_message = Message(
        id=str(uuid4()),
        app_id="app-1",
        conversation_id=str(uuid4()),
        _inputs={},
        query="second preview",
        message={},
        message_unit_price=Decimal(0),
        answer="answer",
        answer_unit_price=Decimal(0),
        currency="USD",
        from_source=ConversationFromSource.API,
    )
    sqlite_session.add_all(
        [
            second_message,
            MessageFile(
                message_id=second_message.id,
                type=FileType.IMAGE,
                transfer_method=FileTransferMethod.LOCAL_FILE,
                created_by_role=CreatorUserRole.END_USER,
                created_by="end-user-1",
                upload_file_id=upload.id,
            ),
        ]
    )
    sqlite_session.commit()
    storage = SimpleNamespace(load=lambda _key, *, stream: [b"content"] if stream else b"content")
    gateway = SqlAlchemyServiceApiFileGateway(session_factory=sqlite_session_factory)

    with patch("services.service_api_file_gateway.storage", storage):
        preview = gateway.preview(
            ServiceApiRequestContext(tenant_id="tenant-1", app_id="app-1"),
            file_id=upload.id,
        )

    assert list(preview.body) == [b"content"]


@pytest.mark.parametrize(
    "context",
    [
        ServiceApiRequestContext(tenant_id="tenant-1", app_id="other-app"),
        ServiceApiRequestContext(tenant_id="other-tenant", app_id="app-1"),
    ],
)
def test_preview_enforces_app_and_tenant_scope(
    sqlite_session: Session,
    sqlite_session_factory: sessionmaker[Session],
    context: ServiceApiRequestContext,
) -> None:
    upload = _persist_preview(sqlite_session)
    gateway = SqlAlchemyServiceApiFileGateway(session_factory=sqlite_session_factory)

    with pytest.raises(ServiceApiFileAccessDeniedError):
        gateway.preview(context, file_id=upload.id)


def test_preview_rejects_unknown_file(sqlite_session_factory: sessionmaker[Session]) -> None:
    gateway = SqlAlchemyServiceApiFileGateway(session_factory=sqlite_session_factory)

    with pytest.raises(ServiceApiFileNotFoundError):
        gateway.preview(
            ServiceApiRequestContext(tenant_id="tenant-1", app_id="app-1"),
            file_id=str(uuid4()),
        )


def test_audio_to_text_preserves_the_incoming_stream(
    sqlite_session_factory: sessionmaker[Session],
) -> None:
    gateway = SqlAlchemyServiceApiFileGateway(session_factory=sqlite_session_factory)
    context = ServiceApiRequestContext(
        tenant_id="tenant-1",
        app_id="app-1",
        end_user=ServiceApiEndUserIdentity(id="end-user-1", external_user_id="external-1"),
    )
    stream = BytesIO(b"audio")

    with (
        patch.object(gateway, "_load_app", return_value=SimpleNamespace(id="app-1")),
        patch("services.service_api_file_gateway.AudioService.transcript_asr", return_value={"text": "hello"}) as asr,
    ):
        result = gateway.audio_to_text(
            context,
            filename="sample.mp3",
            stream=stream,
            mimetype="audio/mpeg",
        )

    assert result == {"text": "hello"}
    passed_file = asr.call_args.kwargs["file"]
    assert passed_file.stream is stream
