"""V2 REST SDK client for compute session sharing (BEP-1073)."""

from __future__ import annotations

from uuid import UUID

from ai.backend.client.v2.base_domain import BaseDomainClient
from ai.backend.common.dto.manager.v2.session_share.request import (
    CreateSessionShareInput,
    SearchSessionSharesInput,
)
from ai.backend.common.dto.manager.v2.session_share.response import (
    CreateSessionSharePayload,
    DeleteSessionSharePayload,
    SearchSessionSharesPayload,
)

_PATH = "/v2/sessions"


class V2SessionShareClient(BaseDomainClient):
    """SDK client for ``/v2/sessions/{session_id}/shares`` endpoints."""

    async def create(
        self,
        session_id: UUID,
        request: CreateSessionShareInput,
    ) -> CreateSessionSharePayload:
        """Share a session with a member of its project (or change the level)."""
        return await self._client.typed_request(
            "POST",
            f"{_PATH}/{session_id}/shares",
            request=request,
            response_model=CreateSessionSharePayload,
        )

    async def search(
        self,
        session_id: UUID,
        request: SearchSessionSharesInput,
    ) -> SearchSessionSharesPayload:
        """List the invitees of a session."""
        return await self._client.typed_request(
            "POST",
            f"{_PATH}/{session_id}/shares/search",
            request=request,
            response_model=SearchSessionSharesPayload,
        )

    async def delete(self, session_id: UUID, user_id: UUID) -> DeleteSessionSharePayload:
        """Revoke a user's access to a shared session."""
        return await self._client.typed_request(
            "DELETE",
            f"{_PATH}/{session_id}/shares/{user_id}",
            response_model=DeleteSessionSharePayload,
        )
