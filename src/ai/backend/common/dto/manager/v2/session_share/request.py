"""
Request DTOs for session share v2.
"""

from __future__ import annotations

from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from ai.backend.common.api_handlers import BaseRequestModel
from ai.backend.common.dto.manager.v2.session_share.types import SessionShareLevelDTO


class CreateSessionShareInput(BaseRequestModel):
    """Input for sharing a session with a user of the same project.

    Exactly one of ``user_id`` and ``email`` identifies the invitee.
    Sharing again with the same user replaces the level.
    """

    user_id: UUID | None = Field(default=None, description="Invitee user ID")
    email: str | None = Field(default=None, description="Invitee email address")
    level: SessionShareLevelDTO = Field(
        default=SessionShareLevelDTO.APP,
        description="'app' to view the session and open its apps, 'execute' to also use the execute API",
    )

    @model_validator(mode="after")
    def _one_invitee(self) -> Self:
        if (self.user_id is None) == (self.email is None):
            raise ValueError("Specify exactly one of user_id and email")
        return self


class SearchSessionSharesInput(BaseRequestModel):
    """Input for listing the invitees of a session."""

    limit: int = Field(default=50, ge=1, le=1000, description="Maximum number of items to return")
    offset: int = Field(default=0, ge=0, description="Number of items to skip")
