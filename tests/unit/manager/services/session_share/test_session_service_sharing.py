"""
Tests for the invitee paths of SessionService (BEP-1073): whose identity opens an app,
and how execute/interrupt reach a session shared with the requester.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai.backend.common.contexts.user import with_user
from ai.backend.common.data.permission.types import OperationType
from ai.backend.common.data.user.types import UserData, UserRole
from ai.backend.common.types import AccessKey, SessionId
from ai.backend.manager.data.session_share.types import SessionShareGrant
from ai.backend.manager.errors.kernel import SessionNotFound
from ai.backend.manager.errors.session_share import SessionShareAccessDenied
from ai.backend.manager.repositories.session.repository import SessionRepository
from ai.backend.manager.services.session.service import SessionService

OWNER = uuid.uuid4()
INVITEE = uuid.uuid4()
SESSION = SessionId(uuid.uuid4())
OWNER_AK = AccessKey("OWNERKEY")
INVITEE_AK = "INVITEEKEY"


def _user(user_id: uuid.UUID, *, superadmin: bool = False) -> UserData:
    return UserData(
        user_id=user_id,
        is_authorized=True,
        is_admin=superadmin,
        is_superadmin=superadmin,
        role=UserRole.SUPERADMIN if superadmin else UserRole.USER,
        domain_name="default",
    )


def _grant(*operations: OperationType) -> SessionShareGrant:
    return SessionShareGrant(
        operations=frozenset(operations),
        owner_access_key=str(OWNER_AK),
        invitee_access_key=INVITEE_AK,
    )


@pytest.fixture
def session_repository() -> MagicMock:
    repo = MagicMock(spec=SessionRepository)
    repo.get_session_share_grant = AsyncMock(return_value=_grant())
    repo.get_session_validated = AsyncMock()
    return repo


@pytest.fixture
def service(session_repository: MagicMock) -> SessionService:
    svc = SessionService.__new__(SessionService)
    svc._session_repository = session_repository
    return svc


class TestAppUserIdentity:
    async def test_owner_opens_apps_as_owner(self, service: SessionService) -> None:
        with with_user(_user(OWNER)):
            assert await service._app_user_identity(SESSION, OWNER, OWNER_AK) == (OWNER, OWNER_AK)

    async def test_superadmin_opens_apps_as_owner(self, service: SessionService) -> None:
        with with_user(_user(uuid.uuid4(), superadmin=True)):
            assert await service._app_user_identity(SESSION, OWNER, OWNER_AK) == (OWNER, OWNER_AK)

    async def test_invitee_opens_apps_as_themselves(
        self, service: SessionService, session_repository: MagicMock
    ) -> None:
        session_repository.get_session_share_grant.return_value = _grant(
            OperationType.READ, OperationType.CREATE
        )
        with with_user(_user(INVITEE)):
            identity = await service._app_user_identity(SESSION, OWNER, OWNER_AK)

        assert identity == (INVITEE, AccessKey(INVITEE_AK))

    async def test_user_without_share_is_refused(self, service: SessionService) -> None:
        with with_user(_user(INVITEE)), pytest.raises(SessionShareAccessDenied):
            await service._app_user_identity(SESSION, OWNER, OWNER_AK)


class TestSessionOrShared:
    async def test_own_session_is_returned_directly(
        self, service: SessionService, session_repository: MagicMock
    ) -> None:
        with with_user(_user(OWNER)):
            await service._get_session_or_shared(str(SESSION), OWNER_AK, OperationType.UPDATE)

        session_repository.get_session_share_grant.assert_not_awaited()

    async def test_shared_session_is_looked_up_with_the_owner_key(
        self, service: SessionService, session_repository: MagicMock
    ) -> None:
        shared_row = MagicMock()
        session_repository.get_session_validated.side_effect = [SessionNotFound(), shared_row]
        session_repository.get_session_share_grant.return_value = _grant(
            OperationType.READ, OperationType.CREATE, OperationType.UPDATE
        )
        with with_user(_user(INVITEE)):
            row = await service._get_session_or_shared(
                str(SESSION), AccessKey(INVITEE_AK), OperationType.UPDATE
            )

        assert row is shared_row
        assert session_repository.get_session_validated.await_args_list[1].args[1] == OWNER_AK

    async def test_app_level_share_does_not_allow_execute(
        self, service: SessionService, session_repository: MagicMock
    ) -> None:
        session_repository.get_session_validated.side_effect = SessionNotFound()
        session_repository.get_session_share_grant.return_value = _grant(
            OperationType.READ, OperationType.CREATE
        )
        with with_user(_user(INVITEE)), pytest.raises(SessionNotFound):
            await service._get_session_or_shared(
                str(SESSION), AccessKey(INVITEE_AK), OperationType.UPDATE
            )

    async def test_session_name_is_not_resolved_through_shares(
        self, service: SessionService, session_repository: MagicMock
    ) -> None:
        session_repository.get_session_validated.side_effect = SessionNotFound()
        with with_user(_user(INVITEE)), pytest.raises(SessionNotFound):
            await service._get_session_or_shared(
                "my-session", AccessKey(INVITEE_AK), OperationType.UPDATE
            )
        session_repository.get_session_share_grant.assert_not_awaited()
