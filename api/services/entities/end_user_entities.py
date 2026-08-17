"""Framework- and persistence-neutral end-user data contracts."""

from datetime import datetime
from typing import NamedTuple


class EndUserRecord(NamedTuple):
    id: str
    tenant_id: str
    app_id: str | None
    type: str
    external_user_id: str | None
    name: str | None
    is_anonymous: bool
    session_id: str
    created_at: datetime
    updated_at: datetime
