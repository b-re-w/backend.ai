"""
Tests for SessionShareRepository (BEP-1073) against a real database.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import datetime

import pytest
import sqlalchemy as sa
from dateutil.tz import tzutc

from ai.backend.common.data.permission.types import (
    EntityType,
    OperationType,
    Permission,
    RBACElementType,
    RelationType,
    ScopeType,
)
from ai.backend.common.identifier.domain import DomainID
from ai.backend.common.identifier.resource_group import ResourceGroupID
from ai.backend.common.types import (
    AccessKey,
    ClusterMode,
    DefaultForUnspecified,
    ResourceSlot,
    SessionId,
    SessionResult,
    SessionTypes,
)
from ai.backend.manager.data.group.types import ProjectType
from ai.backend.manager.data.permission.permission_defs import ComputeSessionPermission
from ai.backend.manager.data.permission.role import (
    PermissionResolutionKey,
    ScopeChainPermissionCheckInput,
)
from ai.backend.manager.data.session.types import SessionStatus
from ai.backend.manager.data.session_share.types import SessionShareLevel
from ai.backend.manager.errors.session_share import (
    SessionShareInviteeHasNoRole,
    SessionShareInviteeNotFound,
    SessionShareNotFound,
    SessionShareSessionNotFound,
)
from ai.backend.manager.models.agent.row import AgentRow
from ai.backend.manager.models.container_registry import ContainerRegistryRow
from ai.backend.manager.models.domain import DomainRow
from ai.backend.manager.models.group import AssocGroupUserRow, GroupRow
from ai.backend.manager.models.image import ImageRow
from ai.backend.manager.models.kernel import KernelRow
from ai.backend.manager.models.keypair import KeyPairRow
from ai.backend.manager.models.rbac import UserScope
from ai.backend.manager.models.rbac.context import ClientContext
from ai.backend.manager.models.rbac_models.association_scopes_entities import (
    AssociationScopesEntitiesRow,
)
from ai.backend.manager.models.rbac_models.permission.object_permission import ObjectPermissionRow
from ai.backend.manager.models.rbac_models.permission.permission import PermissionRow
from ai.backend.manager.models.rbac_models.role import RoleRow
from ai.backend.manager.models.rbac_models.user_role import UserRoleRow
from ai.backend.manager.models.resource_policy import (
    KeyPairResourcePolicyRow,
    ProjectResourcePolicyRow,
    UserResourcePolicyRow,
)
from ai.backend.manager.models.resource_slot import ResourceAllocationRow, ResourceSlotTypeRow
from ai.backend.manager.models.scaling_group import ScalingGroupOpts, ScalingGroupRow
from ai.backend.manager.models.session import SessionRow
from ai.backend.manager.models.session.row import get_permission_ctx
from ai.backend.manager.models.user import UserRole, UserRow, UserStatus
from ai.backend.manager.models.utils import ExtendedAsyncSAEngine
from ai.backend.manager.repositories.permission_controller.repository import (
    PermissionControllerRepository,
)
from ai.backend.manager.repositories.session.repository import SessionRepository
from ai.backend.manager.repositories.session_share.repository import SessionShareRepository
from ai.backend.testutils.db import with_tables

DOMAIN = "test-domain"
SHARE_OPS = frozenset({OperationType.READ, OperationType.CREATE, OperationType.UPDATE})


@dataclass(frozen=True)
class ShareWorld:
    owner: uuid.UUID
    invitee: uuid.UUID
    outsider: uuid.UUID
    roleless: uuid.UUID
    project_admin: uuid.UUID
    project: uuid.UUID
    session: SessionId
    ended_session: SessionId


async def _seed(db: ExtendedAsyncSAEngine) -> ShareWorld:
    domain_id = DomainID(uuid.uuid4())
    rg_id = ResourceGroupID(uuid.uuid4())
    world = ShareWorld(
        owner=uuid.uuid4(),
        invitee=uuid.uuid4(),
        outsider=uuid.uuid4(),
        roleless=uuid.uuid4(),
        project_admin=uuid.uuid4(),
        project=uuid.uuid4(),
        session=SessionId(uuid.uuid4()),
        ended_session=SessionId(uuid.uuid4()),
    )
    access_key = AccessKey("SHARETESTKEY0001")
    async with db.begin_session() as sess:
        sess.add(
            DomainRow(
                id=domain_id,
                name=DOMAIN,
                description="",
                is_active=True,
                total_resource_slots=ResourceSlot(),
                allowed_vfolder_hosts={},
                allowed_docker_registries=[],
                integration_id=None,
            )
        )
        sess.add(
            ScalingGroupRow(
                id=rg_id,
                name="default",
                is_active=True,
                is_public=True,
                driver="static",
                driver_opts={},
                scheduler="fifo",
                scheduler_opts=ScalingGroupOpts(),
                wsproxy_addr="http://coordinator:10200",
                wsproxy_api_token="coord-token",
            )
        )
        sess.add(
            UserResourcePolicyRow(
                name="default",
                max_vfolder_count=10,
                max_quota_scope_size=-1,
                max_session_count_per_model_session=10,
                max_customized_image_count=10,
            )
        )
        sess.add(
            ProjectResourcePolicyRow(
                name="default", max_vfolder_count=10, max_quota_scope_size=-1, max_network_count=10
            )
        )
        sess.add(
            KeyPairResourcePolicyRow(
                name="default",
                default_for_unspecified=DefaultForUnspecified.UNLIMITED,
                total_resource_slots=ResourceSlot(),
                max_session_lifetime=0,
                max_concurrent_sessions=10,
                max_concurrent_sftp_sessions=5,
                max_containers_per_session=1,
                idle_timeout=3600,
            )
        )
        await sess.flush()
        for user_id, name, status in [
            (world.owner, "owner", UserStatus.ACTIVE),
            (world.invitee, "invitee", UserStatus.ACTIVE),
            (world.outsider, "outsider", UserStatus.ACTIVE),
            (world.roleless, "roleless", UserStatus.ACTIVE),
            (world.project_admin, "padmin", UserStatus.ACTIVE),
        ]:
            sess.add(
                UserRow(
                    uuid=user_id,
                    username=name,
                    email=f"{name}@example.com",
                    password=None,
                    need_password_change=False,
                    full_name=name,
                    description="",
                    status=status,
                    status_info="",
                    domain_name=DOMAIN,
                    role=UserRole.USER,
                    resource_policy="default",
                    allowed_client_ip=None,
                    totp_key=None,
                    main_access_key=None,
                )
            )
        await sess.flush()
        sess.add(
            KeyPairRow(
                user_id="owner@example.com",
                user=world.owner,
                access_key=access_key,
                secret_key="secret",
                is_active=True,
                is_admin=False,
                resource_policy="default",
                rate_limit=1000,
            )
        )
        sess.add(
            GroupRow(
                id=world.project,
                name="project",
                domain_name=DOMAIN,
                description="",
                is_active=True,
                total_resource_slots=ResourceSlot(),
                allowed_vfolder_hosts={},
                resource_policy="default",
                type=ProjectType.GENERAL,
            )
        )
        await sess.flush()
        for member in (world.owner, world.invitee, world.roleless, world.project_admin):
            sess.add(AssocGroupUserRow(user_id=member, group_id=world.project))
        now = datetime.now(tzutc())
        for sid, session_status in [
            (world.session, SessionStatus.RUNNING),
            (world.ended_session, SessionStatus.TERMINATED),
        ]:
            sess.add(
                SessionRow(
                    id=sid,
                    creation_id=f"c-{str(sid)[:8]}",
                    name=f"session-{session_status.lower()}",
                    session_type=SessionTypes.INTERACTIVE,
                    cluster_mode=ClusterMode.SINGLE_NODE,
                    cluster_size=1,
                    domain_id=domain_id,
                    domain_name=DOMAIN,
                    group_id=world.project,
                    user_uuid=world.owner,
                    access_key=access_key,
                    tag=None,
                    status=session_status,
                    status_info=None,
                    status_data=None,
                    status_history={},
                    result=SessionResult.UNDEFINED,
                    created_at=now,
                    terminated_at=None,
                    starts_at=None,
                    startup_command=None,
                    callback_url=None,
                    occupying_slots=ResourceSlot(),
                    requested_slots=ResourceSlot(),
                    vfolder_mounts=[],
                    environ=None,
                    bootstrap_script=None,
                    use_host_network=False,
                    resource_group_id=rg_id,
                    scaling_group_name="default",
                )
            )
        # Personal roles (a role holding a permission scoped to its user); `roleless` has none.
        for user_id in (world.owner, world.invitee, world.outsider, world.project_admin):
            role = RoleRow(name=f"user-{str(user_id)[:8]}")
            sess.add(role)
            await sess.flush()
            sess.add(UserRoleRow(user_id=user_id, role_id=role.id))
            sess.add(
                PermissionRow(
                    role_id=role.id,
                    scope_type=ScopeType.USER,
                    scope_id=str(user_id),
                    entity_type=EntityType.SESSION,
                    operation=OperationType.READ,
                    permission=Permission.from_operation(OperationType.READ),
                )
            )
        admin_role = RoleRow(name="role_project_admin")
        sess.add(admin_role)
        await sess.flush()
        sess.add(UserRoleRow(user_id=world.project_admin, role_id=admin_role.id))
        sess.add(
            PermissionRow(
                role_id=admin_role.id,
                scope_type=ScopeType.PROJECT,
                scope_id=str(world.project),
                entity_type=EntityType.SESSION,
                operation=OperationType.GRANT_ALL,
                permission=Permission.from_operation(OperationType.GRANT_ALL),
            )
        )
    return world


async def _share_permission_count(db: ExtendedAsyncSAEngine, session_id: uuid.UUID) -> int:
    async with db.begin_readonly_session() as sess:
        return int(
            await sess.scalar(
                sa.select(sa.func.count())
                .select_from(PermissionRow)
                .where(
                    PermissionRow.scope_type == ScopeType.SESSION,
                    PermissionRow.scope_id == str(session_id),
                )
            )
            or 0
        )


async def _ref_edge_count(db: ExtendedAsyncSAEngine, session_id: uuid.UUID) -> int:
    async with db.begin_readonly_session() as sess:
        return int(
            await sess.scalar(
                sa.select(sa.func.count())
                .select_from(AssociationScopesEntitiesRow)
                .where(
                    AssociationScopesEntitiesRow.entity_type == EntityType.SESSION,
                    AssociationScopesEntitiesRow.entity_id == str(session_id),
                    AssociationScopesEntitiesRow.relation_type == RelationType.REF,
                )
            )
            or 0
        )


class TestSessionShareRepository:
    @pytest.fixture
    async def db(
        self, database_connection: ExtendedAsyncSAEngine
    ) -> AsyncGenerator[ExtendedAsyncSAEngine, None]:
        async with with_tables(
            database_connection,
            [
                DomainRow,
                ScalingGroupRow,
                AgentRow,
                UserResourcePolicyRow,
                ProjectResourcePolicyRow,
                KeyPairResourcePolicyRow,
                UserRow,
                GroupRow,
                AssocGroupUserRow,
                KeyPairRow,
                ContainerRegistryRow,
                ImageRow,
                SessionRow,
                KernelRow,
                ResourceSlotTypeRow,
                ResourceAllocationRow,
                RoleRow,
                UserRoleRow,
                PermissionRow,
                ObjectPermissionRow,
                AssociationScopesEntitiesRow,
            ],
        ):
            yield database_connection

    @pytest.fixture
    async def world(self, db: ExtendedAsyncSAEngine) -> ShareWorld:
        return await _seed(db)

    @pytest.fixture
    def repository(self, db: ExtendedAsyncSAEngine) -> SessionShareRepository:
        return SessionShareRepository(db)

    async def test_target_reports_owner_project_and_app_proxy(
        self, repository: SessionShareRepository, world: ShareWorld
    ) -> None:
        target = await repository.get_target(world.session)

        assert (target.owner_id, target.project_id, target.alive) == (
            world.owner,
            world.project,
            True,
        )
        assert (target.appproxy_addr, target.appproxy_token) == (
            "http://coordinator:10200",
            "coord-token",
        )
        assert (await repository.get_target(world.ended_session)).alive is False

    async def test_missing_session_raises(
        self, repository: SessionShareRepository, world: ShareWorld
    ) -> None:
        with pytest.raises(SessionShareSessionNotFound):
            await repository.get_target(uuid.uuid4())

    async def test_project_admin_is_recognized(
        self, repository: SessionShareRepository, world: ShareWorld
    ) -> None:
        assert await repository.is_project_session_admin(world.project_admin, world.project)
        assert not await repository.is_project_session_admin(world.invitee, world.project)

    async def test_invitee_resolves_by_email_or_id(
        self, repository: SessionShareRepository, world: ShareWorld
    ) -> None:
        assert await repository.resolve_invitee(None, "invitee@example.com") == world.invitee
        assert await repository.resolve_invitee(world.invitee, None) == world.invitee
        with pytest.raises(SessionShareInviteeNotFound):
            await repository.resolve_invitee(None, "nobody@example.com")

    async def test_project_membership(
        self, repository: SessionShareRepository, world: ShareWorld
    ) -> None:
        assert await repository.is_project_member(world.invitee, world.project)
        assert not await repository.is_project_member(world.outsider, world.project)

    async def test_share_grants_level_operations_and_ref_edge(
        self, repository: SessionShareRepository, db: ExtendedAsyncSAEngine, world: ShareWorld
    ) -> None:
        share = await repository.upsert(world.session, world.invitee, SessionShareLevel.APP)

        assert (share.user_id, share.level, share.email) == (
            world.invitee,
            SessionShareLevel.APP,
            "invitee@example.com",
        )
        assert await repository.shared_operations(world.invitee, world.session) == frozenset({
            OperationType.READ,
            OperationType.CREATE,
        })
        assert await _ref_edge_count(db, world.session) == 1
        listed = await repository.search(world.session, limit=10, offset=0)
        assert [s.user_id for s in listed.items] == [world.invitee]
        assert listed.total_count == 1

    async def test_resharing_replaces_the_level(
        self, repository: SessionShareRepository, db: ExtendedAsyncSAEngine, world: ShareWorld
    ) -> None:
        await repository.upsert(world.session, world.invitee, SessionShareLevel.APP)
        share = await repository.upsert(world.session, world.invitee, SessionShareLevel.EXECUTE)

        assert share.level is SessionShareLevel.EXECUTE
        assert await repository.shared_operations(world.invitee, world.session) == SHARE_OPS
        assert await _share_permission_count(db, world.session) == 3
        assert await _ref_edge_count(db, world.session) == 1

    async def test_revoke_removes_grants_and_edge(
        self, repository: SessionShareRepository, db: ExtendedAsyncSAEngine, world: ShareWorld
    ) -> None:
        await repository.upsert(world.session, world.invitee, SessionShareLevel.EXECUTE)

        await repository.delete(world.session, world.invitee)

        assert await repository.shared_operations(world.invitee, world.session) == frozenset()
        assert await _ref_edge_count(db, world.session) == 0
        with pytest.raises(SessionShareNotFound):
            await repository.delete(world.session, world.invitee)

    async def test_user_without_personal_role_cannot_receive_a_share(
        self, repository: SessionShareRepository, world: ShareWorld
    ) -> None:
        with pytest.raises(SessionShareInviteeHasNoRole):
            await repository.upsert(world.session, world.roleless, SessionShareLevel.APP)

    async def test_purge_session_removes_every_share(
        self, repository: SessionShareRepository, db: ExtendedAsyncSAEngine, world: ShareWorld
    ) -> None:
        await repository.upsert(world.session, world.invitee, SessionShareLevel.APP)

        await repository.purge_session(world.session)

        assert await _share_permission_count(db, world.session) == 0
        assert await _ref_edge_count(db, world.session) == 0

    async def test_shares_of_ended_sessions_are_ignored_and_purged(
        self, repository: SessionShareRepository, db: ExtendedAsyncSAEngine, world: ShareWorld
    ) -> None:
        await repository.upsert(world.ended_session, world.invitee, SessionShareLevel.APP)
        await repository.upsert(world.session, world.invitee, SessionShareLevel.APP)

        assert await repository.shared_operations(world.invitee, world.ended_session) == frozenset()
        await repository.purge_dead()

        assert await _share_permission_count(db, world.ended_session) == 0
        assert await _ref_edge_count(db, world.ended_session) == 0
        assert await _share_permission_count(db, world.session) == 2

    async def test_session_repository_reports_the_share_grant(
        self, repository: SessionShareRepository, db: ExtendedAsyncSAEngine, world: ShareWorld
    ) -> None:
        await repository.upsert(world.session, world.invitee, SessionShareLevel.EXECUTE)

        grant = await SessionRepository(db).get_session_share_grant(world.session, world.invitee)
        no_grant = await SessionRepository(db).get_session_share_grant(
            world.session, world.outsider
        )

        assert grant.operations == SHARE_OPS
        assert grant.owner_access_key == "SHARETESTKEY0001"
        assert no_grant.operations == frozenset()

    async def test_generic_rbac_checker_honors_the_share(
        self, repository: SessionShareRepository, db: ExtendedAsyncSAEngine, world: ShareWorld
    ) -> None:
        checker = PermissionControllerRepository(db)

        def _check(user_id: uuid.UUID, operation: OperationType) -> ScopeChainPermissionCheckInput:
            return ScopeChainPermissionCheckInput(
                key=PermissionResolutionKey(
                    user_id=user_id,
                    element_type=RBACElementType.SESSION,
                    entity_id=str(world.session),
                    subject_entity_type=RBACElementType.SESSION,
                ),
                operation=operation,
            )

        assert not await checker.check_permission_with_scope_chain(
            _check(world.invitee, OperationType.READ)
        )
        await repository.upsert(world.session, world.invitee, SessionShareLevel.APP)

        assert await checker.check_permission_with_scope_chain(
            _check(world.invitee, OperationType.READ)
        )
        assert await checker.check_permission_with_scope_chain(
            _check(world.invitee, OperationType.CREATE)
        )
        assert not await checker.check_permission_with_scope_chain(
            _check(world.invitee, OperationType.SOFT_DELETE)
        )

    async def test_session_permission_context_includes_shared_sessions(
        self, repository: SessionShareRepository, db: ExtendedAsyncSAEngine, world: ShareWorld
    ) -> None:
        ctx = ClientContext(db, DOMAIN, world.invitee, UserRole.USER)

        async def _visible(permission: ComputeSessionPermission) -> set[uuid.UUID]:
            async with db.connect() as conn:
                perm_ctx = await get_permission_ctx(
                    conn, ctx, UserScope(user_id=world.invitee), permission
                )
                query = await perm_ctx.build_query()
                if query is None:
                    return set()
                rows = (await conn.execute(query)).all()
            return {row.id for row in rows}

        assert world.session not in await _visible(ComputeSessionPermission.READ_ATTRIBUTE)
        await repository.upsert(world.session, world.invitee, SessionShareLevel.APP)

        assert world.session in await _visible(ComputeSessionPermission.READ_ATTRIBUTE)
        assert world.session in await _visible(ComputeSessionPermission.START_APP)
        assert world.session not in await _visible(ComputeSessionPermission.EXECUTE)
        assert world.ended_session not in await _visible(ComputeSessionPermission.READ_ATTRIBUTE)
