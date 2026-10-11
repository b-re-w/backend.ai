"""Session share adapter bridging DTOs and Processors (BEP-1073)."""

from __future__ import annotations

import uuid

from ai.backend.common.dto.manager.v2.session_share.request import (
    CreateSessionShareInput,
    SearchSessionSharesInput,
)
from ai.backend.common.dto.manager.v2.session_share.response import (
    CreateSessionSharePayload,
    DeleteSessionSharePayload,
    SearchSessionSharesPayload,
    SessionShareNode,
)
from ai.backend.common.dto.manager.v2.session_share.types import SessionShareLevelDTO
from ai.backend.manager.api.adapters.base import BaseAdapter
from ai.backend.manager.data.session_share.types import SessionShareData, SessionShareLevel
from ai.backend.manager.services.session_share.actions.create import CreateSessionShareAction
from ai.backend.manager.services.session_share.actions.delete import DeleteSessionShareAction
from ai.backend.manager.services.session_share.actions.search import SearchSessionSharesAction


class SessionShareAdapter(BaseAdapter):
    """Adapter for session share operations."""

    async def create(
        self, session_id: uuid.UUID, input: CreateSessionShareInput
    ) -> CreateSessionSharePayload:
        """Share a session with a member of its project (or change the level)."""
        result = await self._processors.session_share.create.wait_for_complete(
            CreateSessionShareAction(
                session_id=session_id,
                invitee_user_id=input.user_id,
                invitee_email=input.email,
                level=SessionShareLevel(input.level.value),
            )
        )
        return CreateSessionSharePayload(share=self._to_node(result.share))

    async def delete(self, session_id: uuid.UUID, user_id: uuid.UUID) -> DeleteSessionSharePayload:
        """Revoke a user's access to a shared session."""
        result = await self._processors.session_share.delete.wait_for_complete(
            DeleteSessionShareAction(session_id=session_id, user_id=user_id)
        )
        return DeleteSessionSharePayload(session_id=result.session_id, user_id=result.user_id)

    async def search(
        self, session_id: uuid.UUID, input: SearchSessionSharesInput
    ) -> SearchSessionSharesPayload:
        """List the invitees of a session."""
        result = await self._processors.session_share.search.wait_for_complete(
            SearchSessionSharesAction(session_id=session_id, limit=input.limit, offset=input.offset)
        )
        return SearchSessionSharesPayload(
            items=[self._to_node(share) for share in result.items],
            total_count=result.total_count,
            has_next_page=result.has_next_page,
            has_previous_page=result.has_previous_page,
        )

    @staticmethod
    def _to_node(share: SessionShareData) -> SessionShareNode:
        return SessionShareNode(
            session_id=share.session_id,
            user_id=share.user_id,
            email=share.email,
            username=share.username,
            level=SessionShareLevelDTO(share.level.value),
            created_at=share.created_at,
        )
