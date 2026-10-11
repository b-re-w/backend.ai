"""
Tests for SessionShareService (BEP-1073) with mocked repository and app-proxy client.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from ai.backend.common.contexts.user import with_user
from ai.backend.common.data.user.types import UserData, UserRole
from ai.backend.manager.clients.appproxy.client import AppProxyClientPool
from ai.backend.manager.data.session_share.types import (
    SessionShareData,
    SessionShareLevel,
    SessionShareListResult,
    SessionShareTarget,
)
from ai.backend.manager.errors.session_share import (
    SessionShareForbidden,
    SessionShareInvalidInvitee,
    SessionShareSessionNotFound,
)
from ai.backend.manager.repositories.session_share.repository import SessionShareRepository
from ai.backend.manager.services.session_share.actions.create import CreateSessionShareAction
from ai.backend.manager.services.session_share.actions.delete import DeleteSessionShareAction
from ai.backend.manager.services.session_share.actions.search import SearchSessionSharesAction
from ai.backend.manager.services.session_share.service import SessionShareService

OWNER = uuid.uuid4()
INVITEE = uuid.uuid4()
OUTSIDER = uuid.uuid4()
PROJECT = uuid.uuid4()
SESSION = uuid.uuid4()


def _user(user_id: uuid.UUID, *, superadmin: bool = False) -> UserData:
    return UserData(
        user_id=user_id,
        is_authorized=True,
        is_admin=superadmin,
        is_superadmin=superadmin,
        role=UserRole.SUPERADMIN if superadmin else UserRole.USER,
        domain_name="default",
    )


def _target(
    *, alive: bool = True, appproxy_addr: str | None = "http://coordinator"
) -> SessionShareTarget:
    return SessionShareTarget(
        session_id=SESSION,
        owner_id=OWNER,
        project_id=PROJECT,
        alive=alive,
        appproxy_addr=appproxy_addr,
        appproxy_token="token",
    )


def _share(level: SessionShareLevel = SessionShareLevel.APP) -> SessionShareData:
    return SessionShareData(
        session_id=SESSION,
        user_id=INVITEE,
        email="invitee@example.com",
        username="invitee",
        level=level,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def repository() -> MagicMock:
    repo = MagicMock(spec=SessionShareRepository)
    repo.get_target = AsyncMock(return_value=_target())
    repo.is_project_session_admin = AsyncMock(return_value=False)
    repo.resolve_invitee = AsyncMock(return_value=INVITEE)
    repo.is_project_member = AsyncMock(return_value=True)
    repo.purge_dead = AsyncMock(return_value=0)
    repo.upsert = AsyncMock(return_value=_share())
    repo.delete = AsyncMock(return_value=None)
    repo.search = AsyncMock(
        return_value=SessionShareListResult(
            items=[_share()], total_count=1, has_next_page=False, has_previous_page=False
        )
    )
    return repo


@pytest.fixture
def appproxy_client() -> MagicMock:
    client = MagicMock()
    client.delete_session_user_circuits = AsyncMock(return_value=None)
    return client


@pytest.fixture
def appproxy_pool(appproxy_client: MagicMock) -> MagicMock:
    pool = MagicMock(spec=AppProxyClientPool)
    pool.load_client = MagicMock(return_value=appproxy_client)
    return pool


@pytest.fixture
def service(repository: MagicMock, appproxy_pool: MagicMock) -> SessionShareService:
    return SessionShareService(repository, appproxy_client_pool=appproxy_pool)


@pytest.fixture
def as_owner() -> Iterator[None]:
    with with_user(_user(OWNER)):
        yield


def _create_action(level: SessionShareLevel = SessionShareLevel.APP) -> CreateSessionShareAction:
    return CreateSessionShareAction(
        session_id=SESSION, invitee_user_id=None, invitee_email="invitee@example.com", level=level
    )


class TestCreateSessionShare:
    @pytest.mark.usefixtures("as_owner")
    async def test_owner_shares_with_project_member(
        self, service: SessionShareService, repository: MagicMock
    ) -> None:
        result = await service.create(_create_action(SessionShareLevel.EXECUTE))

        assert result.share.user_id == INVITEE
        repository.upsert.assert_awaited_once_with(SESSION, INVITEE, SessionShareLevel.EXECUTE)
        repository.resolve_invitee.assert_awaited_once_with(None, "invitee@example.com")

    async def test_project_admin_may_share(
        self, service: SessionShareService, repository: MagicMock
    ) -> None:
        admin = uuid.uuid4()
        repository.is_project_session_admin.return_value = True
        with with_user(_user(admin)):
            await service.create(_create_action())

        repository.is_project_session_admin.assert_awaited_once_with(admin, PROJECT)
        repository.upsert.assert_awaited_once()

    async def test_superadmin_may_share(
        self, service: SessionShareService, repository: MagicMock
    ) -> None:
        with with_user(_user(uuid.uuid4(), superadmin=True)):
            await service.create(_create_action())

        repository.is_project_session_admin.assert_not_awaited()
        repository.upsert.assert_awaited_once()

    async def test_other_user_is_forbidden(
        self, service: SessionShareService, repository: MagicMock
    ) -> None:
        with with_user(_user(OUTSIDER)), pytest.raises(SessionShareForbidden):
            await service.create(_create_action())
        repository.upsert.assert_not_awaited()

    @pytest.mark.usefixtures("as_owner")
    async def test_ended_session_cannot_be_shared(
        self, service: SessionShareService, repository: MagicMock
    ) -> None:
        repository.get_target.return_value = _target(alive=False)
        with pytest.raises(SessionShareSessionNotFound):
            await service.create(_create_action())
        repository.upsert.assert_not_awaited()

    @pytest.mark.usefixtures("as_owner")
    async def test_owner_cannot_be_invited(
        self, service: SessionShareService, repository: MagicMock
    ) -> None:
        repository.resolve_invitee.return_value = OWNER
        with pytest.raises(SessionShareInvalidInvitee):
            await service.create(_create_action())
        repository.upsert.assert_not_awaited()

    @pytest.mark.usefixtures("as_owner")
    async def test_invitee_outside_project_is_rejected(
        self, service: SessionShareService, repository: MagicMock
    ) -> None:
        repository.is_project_member.return_value = False
        with pytest.raises(SessionShareInvalidInvitee):
            await service.create(_create_action())
        repository.upsert.assert_not_awaited()


class TestDeleteSessionShare:
    @pytest.mark.usefixtures("as_owner")
    async def test_revoke_drops_app_circuits(
        self,
        service: SessionShareService,
        repository: MagicMock,
        appproxy_pool: MagicMock,
        appproxy_client: MagicMock,
    ) -> None:
        result = await service.delete(DeleteSessionShareAction(session_id=SESSION, user_id=INVITEE))

        assert (result.session_id, result.user_id) == (SESSION, INVITEE)
        repository.delete.assert_awaited_once_with(SESSION, INVITEE)
        appproxy_pool.load_client.assert_called_once_with("http://coordinator", "token")
        appproxy_client.delete_session_user_circuits.assert_awaited_once_with(SESSION, INVITEE)

    @pytest.mark.usefixtures("as_owner")
    async def test_revoke_succeeds_when_app_proxy_fails(
        self, service: SessionShareService, repository: MagicMock, appproxy_client: MagicMock
    ) -> None:
        appproxy_client.delete_session_user_circuits.side_effect = aiohttp.ClientError("down")

        await service.delete(DeleteSessionShareAction(session_id=SESSION, user_id=INVITEE))

        repository.delete.assert_awaited_once_with(SESSION, INVITEE)

    @pytest.mark.usefixtures("as_owner")
    async def test_revoke_without_app_proxy_skips_circuits(
        self, service: SessionShareService, repository: MagicMock, appproxy_pool: MagicMock
    ) -> None:
        repository.get_target.return_value = _target(appproxy_addr=None)

        await service.delete(DeleteSessionShareAction(session_id=SESSION, user_id=INVITEE))

        appproxy_pool.load_client.assert_not_called()

    async def test_other_user_cannot_revoke(
        self, service: SessionShareService, repository: MagicMock
    ) -> None:
        with with_user(_user(OUTSIDER)), pytest.raises(SessionShareForbidden):
            await service.delete(DeleteSessionShareAction(session_id=SESSION, user_id=INVITEE))
        repository.delete.assert_not_awaited()


class TestSearchSessionShares:
    @pytest.mark.usefixtures("as_owner")
    async def test_owner_lists_invitees(
        self, service: SessionShareService, repository: MagicMock
    ) -> None:
        result = await service.search(
            SearchSessionSharesAction(session_id=SESSION, limit=10, offset=0)
        )

        assert [s.user_id for s in result.items] == [INVITEE]
        assert result.total_count == 1
        repository.search.assert_awaited_once_with(SESSION, 10, 0)

    async def test_other_user_cannot_list(self, service: SessionShareService) -> None:
        with with_user(_user(OUTSIDER)), pytest.raises(SessionShareForbidden):
            await service.search(SearchSessionSharesAction(session_id=SESSION, limit=10, offset=0))
