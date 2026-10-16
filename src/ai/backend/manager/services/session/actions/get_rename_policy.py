from dataclasses import dataclass
from typing import override

from ai.backend.manager.actions.action import BaseActionResult
from ai.backend.manager.actions.types import ActionOperationType
from ai.backend.manager.services.session.base import SessionAction


@dataclass
class GetSessionRenamePolicyAction(SessionAction):
    """Whether admins may rename other users' sessions (``session.allow-admin-rename``)."""

    @override
    def entity_id(self) -> str | None:
        return None

    @override
    @classmethod
    def operation_type(cls) -> ActionOperationType:
        return ActionOperationType.GET


@dataclass
class GetSessionRenamePolicyActionResult(BaseActionResult):
    admin_rename_enabled: bool

    @override
    def entity_id(self) -> str | None:
        return None
