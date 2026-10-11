"""
Response DTOs for session share v2.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from ai.backend.common.api_handlers import BaseResponseModel
from ai.backend.common.dto.manager.v2.session_share.types import SessionShareLevelDTO


class SessionShareNode(BaseResponseModel):
    """An invitee of a shared session."""

    session_id: UUID = Field(description="Shared session ID")
    user_id: UUID = Field(description="Invitee user ID")
    email: str = Field(description="Invitee email address")
    username: str | None = Field(default=None, description="Invitee username")
    level: SessionShareLevelDTO = Field(description="Share level")
    created_at: datetime | None = Field(default=None, description="When the share was granted")


class CreateSessionSharePayload(BaseResponseModel):
    """Payload for a created or updated share."""

    share: SessionShareNode = Field(description="The share")


class DeleteSessionSharePayload(BaseResponseModel):
    """Payload for a revoked share."""

    session_id: UUID = Field(description="Session ID")
    user_id: UUID = Field(description="User ID whose access was revoked")


class SearchSessionSharesPayload(BaseResponseModel):
    """Paginated invitees of a session."""

    items: list[SessionShareNode] = Field(description="Invitees")
    total_count: int = Field(description="Total number of invitees")
    has_next_page: bool = Field(description="Whether there is a next page")
    has_previous_page: bool = Field(description="Whether there is a previous page")
