"""Response contracts shared by Service API workflow adapters."""

from collections.abc import Mapping
from datetime import datetime

from pydantic import Field, field_validator, model_validator

from fields.base import ResponseModel
from fields.end_user_fields import SimpleEndUser
from fields.member_fields import SimpleAccountResponse
from graphon.enums import WorkflowExecutionStatus
from libs.helper import to_timestamp


def _enum_value(value):
    return getattr(value, "value", value)


class WorkflowRunResponse(ResponseModel):
    id: str
    workflow_id: str
    status: str
    inputs: str | None = None
    outputs: dict = Field(default_factory=dict, validation_alias="outputs_dict")
    error: str | None = None
    total_steps: int | None = None
    total_tokens: int | None = None
    created_at: int | None = None
    finished_at: int | None = None
    elapsed_time: float | int | None = None

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_enum(cls, value):
        return _enum_value(value)

    @field_validator("outputs", mode="before")
    @classmethod
    def _normalize_outputs(cls, value):
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        if isinstance(value, Mapping):
            return dict(value)
        return {}

    @field_validator("created_at", "finished_at", mode="before")
    @classmethod
    def _normalize_timestamp(cls, value: datetime | int | None) -> int | None:
        return to_timestamp(value)

    @model_validator(mode="after")
    def _clear_paused_outputs(self):
        if self.status == WorkflowExecutionStatus.PAUSED.value:
            self.outputs = {}
        return self


class WorkflowRunForLogResponse(ResponseModel):
    id: str
    version: str | None = None
    status: str | None = None
    triggered_from: str | None = None
    error: str | None = None
    elapsed_time: float | int | None = None
    total_tokens: int | None = None
    total_steps: int | None = None
    created_at: int | None = None
    finished_at: int | None = None
    exceptions_count: int | None = None

    @field_validator("status", "triggered_from", mode="before")
    @classmethod
    def _normalize_enum(cls, value):
        return _enum_value(value)

    @field_validator("created_at", "finished_at", mode="before")
    @classmethod
    def _normalize_timestamp(cls, value: datetime | int | None) -> int | None:
        return to_timestamp(value)


class WorkflowAppLogPartialResponse(ResponseModel):
    id: str
    workflow_run: WorkflowRunForLogResponse | None = None
    details: dict | list | str | int | float | bool | None = Field(default=None)
    created_from: str | None = None
    created_by_role: str | None = None
    created_by_account: SimpleAccountResponse | None = None
    created_by_end_user: SimpleEndUser | None = None
    created_at: int | None = None

    @field_validator("created_from", "created_by_role", mode="before")
    @classmethod
    def _normalize_enum(cls, value):
        return _enum_value(value)

    @field_validator("created_at", mode="before")
    @classmethod
    def _normalize_timestamp(cls, value: datetime | int | None) -> int | None:
        return to_timestamp(value)


class WorkflowAppLogPaginationResponse(ResponseModel):
    page: int
    limit: int
    total: int
    has_more: bool
    data: list[WorkflowAppLogPartialResponse]
