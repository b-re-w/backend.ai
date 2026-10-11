"""REST v2 handler for compute session sharing (BEP-1073)."""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import TYPE_CHECKING, Final

from ai.backend.common.api_handlers import APIResponse, BodyParam, PathParam
from ai.backend.common.dto.manager.v2.session_share.request import (
    CreateSessionShareInput,
    SearchSessionSharesInput,
)
from ai.backend.logging import BraceStyleAdapter
from ai.backend.manager.api.rest.v2.path_params import (
    SessionIdPathParam,
    SessionShareUserPathParam,
)

if TYPE_CHECKING:
    from ai.backend.manager.api.adapters.session_share.adapter import SessionShareAdapter

log: Final = BraceStyleAdapter(logging.getLogger(__spec__.name))


class V2SessionShareHandler:
    """REST v2 handler for session share operations."""

    def __init__(self, *, adapter: SessionShareAdapter) -> None:
        self._adapter = adapter

    async def create(
        self,
        path: PathParam[SessionIdPathParam],
        body: BodyParam[CreateSessionShareInput],
    ) -> APIResponse:
        """Share the session with a member of its project (or change the level)."""
        result = await self._adapter.create(path.parsed.session_id, body.parsed)
        return APIResponse.build(status_code=HTTPStatus.CREATED, response_model=result)

    async def search(
        self,
        path: PathParam[SessionIdPathParam],
        body: BodyParam[SearchSessionSharesInput],
    ) -> APIResponse:
        """List the invitees of the session."""
        result = await self._adapter.search(path.parsed.session_id, body.parsed)
        return APIResponse.build(status_code=HTTPStatus.OK, response_model=result)

    async def delete(
        self,
        path: PathParam[SessionShareUserPathParam],
    ) -> APIResponse:
        """Revoke a user's access to the session."""
        result = await self._adapter.delete(path.parsed.session_id, path.parsed.user_id)
        return APIResponse.build(status_code=HTTPStatus.OK, response_model=result)
