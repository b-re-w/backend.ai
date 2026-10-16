"""
Renaming another user's session as an admin, gated by session.allow-admin-rename (off by default).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai.backend.common.contexts.user import with_user
from ai.backend.common.data.user.types import UserData, UserRole
from ai.backend.common.types import AccessKey, SessionId
from ai.backend.manager.data.session.types import SessionStatus
from ai.backend.manager.errors.kernel import SessionAdminRenameDisabled, SessionNotFound
from ai.backend.manager.repositories.session.repository import SessionRepository
from ai.backend.manager.services.session.actions.get_rename_policy import (
    GetSessionRenamePolicyAction,
)
from ai.backend.manager.services.session.actions.rename_session import RenameSessionAction
from ai.backend.manager.services.session.service import SessionService

SESSION = SessionId(uuid.uuid4())
OWNER_KEY = AccessKey("OWNERKEY")
ADMIN_KEY = AccessKey("ADMINKEY")
DOMAIN = "default"


def _user(role: UserRole, domain: str = DOMAIN) -> UserData:
    return UserData(
        user_id=uuid.uuid4(),
        is_authorized=True,
        is_admin=role in (UserRole.ADMIN, UserRole.SUPERADMIN),
        is_superadmin=role is UserRole.SUPERADMIN,
        role=role,
        domain_name=domain,
    )


def _service(repository: MagicMock, allow: object) -> SessionService:
    service = SessionService.__new__(SessionService)
    service._session_repository = repository
    if allow is None:
        service._config_provider = None
    else:
        provider = MagicMock()
        provider.config.session.allow_admin_rename = allow
        service._config_provider = provider
    return service


@pytest.fixture
def repository() -> MagicMock:
    """A session owned by someone else: the requester's own lookup finds nothing."""
    repo = MagicMock(spec=SessionRepository)
    repo.get_session_validated = AsyncMock(side_effect=SessionNotFound())
    repo.get_session_access_scope = AsyncMock(return_value=(OWNER_KEY, DOMAIN))
    renamed = MagicMock()
    renamed.status = SessionStatus.RUNNING
    repo.update_session_name = AsyncMock(return_value=renamed)
    return repo


def _rename(name: str = str(SESSION)) -> RenameSessionAction:
    return RenameSessionAction(session_name=name, new_name="renamed", owner_access_key=ADMIN_KEY)


class TestOwnerRename:
    async def test_owner_renames_without_the_setting(self, repository: MagicMock) -> None:
        repository.get_session_validated = AsyncMock()
        service = _service(repository, allow=False)

        with with_user(_user(UserRole.USER)):
            await service.rename_session(_rename("my-session"))

        repository.update_session_name.assert_awaited_once_with("my-session", "renamed", ADMIN_KEY)


class TestAdminRename:
    async def test_superadmin_renames_another_users_session_when_allowed(
        self, repository: MagicMock
    ) -> None:
        service = _service(repository, allow=True)

        with with_user(_user(UserRole.SUPERADMIN, domain="other")):
            await service.rename_session(_rename())

        repository.update_session_name.assert_awaited_once_with(str(SESSION), "renamed", OWNER_KEY)

    async def test_domain_admin_renames_sessions_in_their_domain_when_allowed(
        self, repository: MagicMock
    ) -> None:
        service = _service(repository, allow=True)

        with with_user(_user(UserRole.ADMIN)):
            await service.rename_session(_rename())

        repository.update_session_name.assert_awaited_once_with(str(SESSION), "renamed", OWNER_KEY)

    async def test_domain_admin_cannot_reach_another_domain(self, repository: MagicMock) -> None:
        service = _service(repository, allow=True)

        with with_user(_user(UserRole.ADMIN, domain="other")), pytest.raises(SessionNotFound):
            await service.rename_session(_rename())
        repository.update_session_name.assert_not_awaited()

    @pytest.mark.parametrize("allow", [False, None, "true", 1])
    async def test_admin_rename_is_off_unless_explicitly_true(
        self, repository: MagicMock, allow: object
    ) -> None:
        service = _service(repository, allow=allow)

        with with_user(_user(UserRole.SUPERADMIN)), pytest.raises(SessionAdminRenameDisabled):
            await service.rename_session(_rename())
        repository.update_session_name.assert_not_awaited()

    async def test_regular_user_cannot_rename_another_users_session(
        self, repository: MagicMock
    ) -> None:
        service = _service(repository, allow=True)

        with with_user(_user(UserRole.USER)), pytest.raises(SessionNotFound):
            await service.rename_session(_rename())
        repository.update_session_name.assert_not_awaited()

    async def test_admin_must_reference_the_session_by_id(self, repository: MagicMock) -> None:
        service = _service(repository, allow=True)

        with with_user(_user(UserRole.SUPERADMIN)), pytest.raises(SessionNotFound):
            await service.rename_session(_rename("someones-session"))
        repository.update_session_name.assert_not_awaited()


class TestRenamePolicy:
    @pytest.mark.parametrize(("allow", "expected"), [(True, True), (False, False), (None, False)])
    async def test_reports_the_setting(
        self, repository: MagicMock, allow: object, expected: bool
    ) -> None:
        service = _service(repository, allow=allow)

        result = await service.get_rename_policy(GetSessionRenamePolicyAction())

        assert result.admin_rename_enabled is expected
