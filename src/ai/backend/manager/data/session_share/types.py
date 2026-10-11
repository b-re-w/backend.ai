"""Data types for compute session sharing (BEP-1073)."""

from __future__ import annotations

import enum
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from ai.backend.common.data.permission.types import OperationType
from ai.backend.manager.data.session.types import SessionStatus


class SessionShareLevel(enum.StrEnum):
    """What an invitee may do in a shared session."""

    APP = "app"
    EXECUTE = "execute"

    def operations(self) -> frozenset[OperationType]:
        """RBAC operations granted on the session for this level."""
        return SESSION_SHARE_LEVEL_OPERATIONS[self]

    @classmethod
    def from_operations(cls, operations: frozenset[OperationType]) -> SessionShareLevel:
        """The level an invitee's granted operations amount to."""
        if OperationType.UPDATE in operations:
            return cls.EXECUTE
        return cls.APP


SESSION_SHARE_LEVEL_OPERATIONS: Final[Mapping[SessionShareLevel, frozenset[OperationType]]] = {
    SessionShareLevel.APP: frozenset({OperationType.READ, OperationType.CREATE}),
    SessionShareLevel.EXECUTE: frozenset({
        OperationType.READ,
        OperationType.CREATE,
        OperationType.UPDATE,
    }),
}

# Every operation a share may grant; revoking removes all of them.
SESSION_SHARE_OPERATIONS: Final[frozenset[OperationType]] = SESSION_SHARE_LEVEL_OPERATIONS[
    SessionShareLevel.EXECUTE
]

# A share is live only while the session is alive.
SESSION_SHARE_DEAD_STATUSES: Final[frozenset[SessionStatus]] = frozenset({
    SessionStatus.TERMINATING,
    SessionStatus.TERMINATED,
    SessionStatus.ERROR,
    SessionStatus.CANCELLED,
})


@dataclass(frozen=True)
class SessionShareData:
    session_id: uuid.UUID
    user_id: uuid.UUID
    email: str
    username: str | None
    level: SessionShareLevel
    created_at: datetime | None


@dataclass(frozen=True)
class SessionShareListResult:
    items: list[SessionShareData]
    total_count: int
    has_next_page: bool
    has_previous_page: bool


@dataclass(frozen=True)
class SessionShareTarget:
    """The session a share request is about, as seen by the manager."""

    session_id: uuid.UUID
    owner_id: uuid.UUID
    project_id: uuid.UUID
    alive: bool
    appproxy_addr: str | None
    appproxy_token: str | None


@dataclass(frozen=True)
class SessionShareGrant:
    """What a user may do on a session through a live share."""

    operations: frozenset[OperationType]
    owner_access_key: str | None
    invitee_access_key: str | None
