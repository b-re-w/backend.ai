from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, override

from ai.backend.common.types import KernelId, SessionId
from ai.backend.manager.actions.action import BaseActionResult
from ai.backend.manager.actions.types import ActionOperationType
from ai.backend.manager.services.stream.actions.base import StreamAction


@dataclass(frozen=True)
class GetStreamingSessionAction(StreamAction):
    session_name: str
    user_uuid: uuid.UUID
    # Set when the caller referenced the session by id; lets a session shared with the user
    # (BEP-1073) be found, since shared sessions cannot be looked up by name.
    session_id: SessionId | None = None

    @override
    def entity_id(self) -> str | None:
        return self.session_name

    @override
    @classmethod
    def operation_type(cls) -> ActionOperationType:
        return ActionOperationType.GET


@dataclass(frozen=True)
class GetStreamingSessionActionResult(BaseActionResult):
    session_id: SessionId
    kernel_id: KernelId
    kernel_host: str | None
    agent_addr: str | None
    repl_in_port: int
    repl_out_port: int
    service_ports: list[dict[str, Any]]

    @override
    def entity_id(self) -> str | None:
        return str(self.session_id)
