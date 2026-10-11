import uuid
from dataclasses import dataclass
from typing import override

from ai.backend.manager.actions.action import BaseActionResult
from ai.backend.manager.actions.types import ActionOperationType
from ai.backend.manager.data.session_share.types import SessionShareData, SessionShareLevel
from ai.backend.manager.services.session_share.actions.base import SessionShareAction


@dataclass
class CreateSessionShareAction(SessionShareAction):
    """Share a session with a member of its project (or change the level)."""

    session_id: uuid.UUID
    invitee_user_id: uuid.UUID | None
    invitee_email: str | None
    level: SessionShareLevel

    @override
    def entity_id(self) -> str | None:
        return str(self.session_id)

    @override
    @classmethod
    def operation_type(cls) -> ActionOperationType:
        return ActionOperationType.CREATE


@dataclass
class CreateSessionShareActionResult(BaseActionResult):
    share: SessionShareData

    @override
    def entity_id(self) -> str | None:
        return str(self.share.session_id)
