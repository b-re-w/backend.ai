import uuid
from dataclasses import dataclass
from typing import override

from ai.backend.manager.actions.action import BaseActionResult
from ai.backend.manager.actions.types import ActionOperationType
from ai.backend.manager.data.session_share.types import SessionShareData
from ai.backend.manager.services.session_share.actions.base import SessionShareAction


@dataclass
class SearchSessionSharesAction(SessionShareAction):
    """List the invitees of a session."""

    session_id: uuid.UUID
    limit: int
    offset: int

    @override
    def entity_id(self) -> str | None:
        return str(self.session_id)

    @override
    @classmethod
    def operation_type(cls) -> ActionOperationType:
        return ActionOperationType.SEARCH


@dataclass
class SearchSessionSharesActionResult(BaseActionResult):
    items: list[SessionShareData]
    total_count: int
    has_next_page: bool
    has_previous_page: bool

    @override
    def entity_id(self) -> str | None:
        return None
