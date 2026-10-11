"""Service for compute session sharing (BEP-1073)."""

from __future__ import annotations

import logging
import uuid

import aiohttp

from ai.backend.common.contexts.user import current_user
from ai.backend.common.exception import UnreachableError
from ai.backend.logging.utils import BraceStyleAdapter
from ai.backend.manager.clients.appproxy.client import AppProxyClientPool
from ai.backend.manager.data.session_share.types import SessionShareTarget
from ai.backend.manager.errors.session_share import (
    SessionShareForbidden,
    SessionShareInvalidInvitee,
    SessionShareSessionNotFound,
)
from ai.backend.manager.repositories.session_share.repository import SessionShareRepository
from ai.backend.manager.services.session_share.actions.create import (
    CreateSessionShareAction,
    CreateSessionShareActionResult,
)
from ai.backend.manager.services.session_share.actions.delete import (
    DeleteSessionShareAction,
    DeleteSessionShareActionResult,
)
from ai.backend.manager.services.session_share.actions.search import (
    SearchSessionSharesAction,
    SearchSessionSharesActionResult,
)

log = BraceStyleAdapter(logging.getLogger(__spec__.name))


class SessionShareService:
    """Shares are managed by the session owner, a project admin of its project, or a superadmin."""

    _repository: SessionShareRepository
    _appproxy_client_pool: AppProxyClientPool

    def __init__(
        self,
        repository: SessionShareRepository,
        appproxy_client_pool: AppProxyClientPool,
    ) -> None:
        self._repository = repository
        self._appproxy_client_pool = appproxy_client_pool

    async def create(self, action: CreateSessionShareAction) -> CreateSessionShareActionResult:
        target = await self._managed_target(action.session_id)
        if not target.alive:
            raise SessionShareSessionNotFound(f"Session {action.session_id} is not running.")
        invitee = await self._repository.resolve_invitee(
            action.invitee_user_id, action.invitee_email
        )
        if invitee == target.owner_id:
            raise SessionShareInvalidInvitee("The owner already has access to the session.")
        if not await self._repository.is_project_member(invitee, target.project_id):
            raise SessionShareInvalidInvitee(
                "The invitee is not a member of the session's project."
            )
        await self._repository.purge_dead()
        share = await self._repository.upsert(target.session_id, invitee, action.level)
        log.info(
            "session {} shared with user {} (level: {})", target.session_id, invitee, action.level
        )
        return CreateSessionShareActionResult(share=share)

    async def delete(self, action: DeleteSessionShareAction) -> DeleteSessionShareActionResult:
        target = await self._managed_target(action.session_id)
        await self._repository.delete(target.session_id, action.user_id)
        log.info("session {} unshared from user {}", target.session_id, action.user_id)
        await self._drop_app_circuits(target, action.user_id)
        return DeleteSessionShareActionResult(session_id=target.session_id, user_id=action.user_id)

    async def search(self, action: SearchSessionSharesAction) -> SearchSessionSharesActionResult:
        target = await self._managed_target(action.session_id)
        result = await self._repository.search(target.session_id, action.limit, action.offset)
        return SearchSessionSharesActionResult(
            items=result.items,
            total_count=result.total_count,
            has_next_page=result.has_next_page,
            has_previous_page=result.has_previous_page,
        )

    async def _managed_target(self, session_id: uuid.UUID) -> SessionShareTarget:
        """The session, if the current user may manage its shares."""
        me = current_user()
        if me is None:
            raise UnreachableError("User context is not available")
        target = await self._repository.get_target(session_id)
        if me.is_superadmin or me.user_id == target.owner_id:
            return target
        if await self._repository.is_project_session_admin(me.user_id, target.project_id):
            return target
        raise SessionShareForbidden()

    async def _drop_app_circuits(self, target: SessionShareTarget, user_id: uuid.UUID) -> None:
        """Cut the revoked user's open apps; the share itself is already gone."""
        if not target.appproxy_addr:
            return
        client = self._appproxy_client_pool.load_client(
            target.appproxy_addr, target.appproxy_token or ""
        )
        try:
            await client.delete_session_user_circuits(target.session_id, user_id)
        except (aiohttp.ClientError, TimeoutError) as e:
            log.warning(
                "could not drop app circuits of user {} on session {}: {!r}",
                user_id,
                target.session_id,
                e,
            )
