from __future__ import annotations

from datetime import datetime

from fields.base import ResponseModel


class SimpleEndUser(ResponseModel):
    id: str
    type: str
    is_anonymous: bool
    session_id: str | None = None


class EndUserDetail(ResponseModel):
    """Full end-user detail returned by the Service API."""

    id: str
    tenant_id: str
    app_id: str | None = None
    type: str
    external_user_id: str | None = None
    name: str | None = None
    is_anonymous: bool
    session_id: str
    created_at: datetime
    updated_at: datetime
