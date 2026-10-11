import uuid
from dataclasses import dataclass
from typing import override

from ai.backend.manager.actions.action import BaseActionResult
from ai.backend.manager.actions.types import ActionOperationType
from ai.backend.manager.services.session_share.actions.base import SessionShareAction


@dataclass
class DeleteSessionShareAction(SessionShareAction):
    """Revoke a user's access to a shared session."""

    session_id: uuid.UUID
    user_id: uuid.UUID

    @override
    def entity_id(self) -> str | None:
        return str(self.session_id)

    @override
    @classmethod
    def operation_type(cls) -> ActionOperationType:
        return ActionOperationType.DELETE


@dataclass
class DeleteSessionShareActionResult(BaseActionResult):
    session_id: uuid.UUID
    user_id: uuid.UUID

    @override
    def entity_id(self) -> str | None:
        return str(self.session_id)
