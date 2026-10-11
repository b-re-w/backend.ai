"""Database source for compute session sharing (BEP-1073).

A share of session S with user U is stored in the BEP-1012
``{entity}:assignment`` shape, so no table of its own is needed:

- a REF edge in ``association_scopes_entities``: scope ``user:U`` -> entity ``session:S``;
- permissions on U's personal role scoped to the session itself
  (``scope_type = session``, ``scope_id = S``, ``entity_type = session``).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast

import sqlalchemy as sa
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession as SASession

from ai.backend.common.data.permission.types import (
    EntityType,
    OperationType,
    Permission,
    RelationType,
    ScopeType,
)
from ai.backend.manager.data.session_share.types import (
    SESSION_SHARE_DEAD_STATUSES,
    SESSION_SHARE_OPERATIONS,
    SessionShareData,
    SessionShareLevel,
    SessionShareListResult,
    SessionShareTarget,
)
from ai.backend.manager.data.user.types import UserStatus
from ai.backend.manager.errors.session_share import (
    SessionShareInviteeHasNoRole,
    SessionShareInviteeNotFound,
    SessionShareNotFound,
    SessionShareSessionNotFound,
)
from ai.backend.manager.models.group.row import AssocGroupUserRow
from ai.backend.manager.models.rbac_models.association_scopes_entities import (
    AssociationScopesEntitiesRow,
)
from ai.backend.manager.models.rbac_models.permission.permission import PermissionRow
from ai.backend.manager.models.rbac_models.user_role import UserRoleRow
from ai.backend.manager.models.scaling_group.row import ScalingGroupRow
from ai.backend.manager.models.session.row import SessionRow
from ai.backend.manager.models.user.row import UserRow
from ai.backend.manager.models.utils import ExtendedAsyncSAEngine


class SessionShareDBSource:
    """Database source for session share operations."""

    _db: ExtendedAsyncSAEngine

    def __init__(self, db: ExtendedAsyncSAEngine) -> None:
        self._db = db

    # ---- reads ----------------------------------------------------------

    async def get_target(self, session_id: uuid.UUID) -> SessionShareTarget:
        async with self._db.begin_readonly_session_read_committed() as db_sess:
            row = (
                await db_sess.execute(
                    sa.select(
                        SessionRow.id,
                        SessionRow.user_uuid,
                        SessionRow.group_id,
                        SessionRow.status,
                        ScalingGroupRow.wsproxy_addr,
                        ScalingGroupRow.wsproxy_api_token,
                    )
                    .select_from(SessionRow)
                    .outerjoin(
                        ScalingGroupRow, ScalingGroupRow.name == SessionRow.scaling_group_name
                    )
                    .where(SessionRow.id == session_id)
                )
            ).first()
        if row is None:
            raise SessionShareSessionNotFound(f"Session {session_id} not found.")
        return SessionShareTarget(
            session_id=row.id,
            owner_id=row.user_uuid,
            project_id=row.group_id,
            alive=row.status not in SESSION_SHARE_DEAD_STATUSES,
            appproxy_addr=row.wsproxy_addr,
            appproxy_token=row.wsproxy_api_token,
        )

    async def is_project_session_admin(self, user_id: uuid.UUID, project_id: uuid.UUID) -> bool:
        """Whether one of the user's roles may grant any session permission in the project."""
        async with self._db.begin_readonly_session_read_committed() as db_sess:
            found = await db_sess.scalar(
                sa.select(sa.literal(1))
                .select_from(PermissionRow)
                .join(UserRoleRow, UserRoleRow.role_id == PermissionRow.role_id)
                .where(
                    UserRoleRow.user_id == user_id,
                    PermissionRow.scope_type == ScopeType.PROJECT,
                    PermissionRow.scope_id == str(project_id),
                    PermissionRow.entity_type == EntityType.SESSION,
                    PermissionRow.operation == OperationType.GRANT_ALL,
                )
                .limit(1)
            )
        return found is not None

    async def resolve_invitee(self, user_id: uuid.UUID | None, email: str | None) -> uuid.UUID:
        cond = UserRow.uuid == user_id if user_id is not None else UserRow.email == email
        async with self._db.begin_readonly_session_read_committed() as db_sess:
            invitee = await db_sess.scalar(
                sa.select(UserRow.uuid).where(cond, UserRow.status == UserStatus.ACTIVE)
            )
        if invitee is None:
            raise SessionShareInviteeNotFound("No active user matches the invitee.")
        return invitee

    async def is_project_member(self, user_id: uuid.UUID, project_id: uuid.UUID) -> bool:
        async with self._db.begin_readonly_session_read_committed() as db_sess:
            found = await db_sess.scalar(
                sa.select(sa.literal(1)).where(
                    AssocGroupUserRow.user_id == user_id,
                    AssocGroupUserRow.group_id == project_id,
                )
            )
        return found is not None

    async def search(
        self, session_id: uuid.UUID, limit: int, offset: int
    ) -> SessionShareListResult:
        async with self._db.begin_readonly_session_read_committed() as db_sess:
            shares = await self._shares_of_session(db_sess, session_id)
        page = shares[offset : offset + limit]
        return SessionShareListResult(
            items=page,
            total_count=len(shares),
            has_next_page=offset + limit < len(shares),
            has_previous_page=offset > 0,
        )

    async def shared_operations(
        self, user_id: uuid.UUID, session_id: uuid.UUID
    ) -> frozenset[OperationType]:
        """Operations granted to the user on the session by a live share (empty if none)."""
        async with self._db.begin_readonly_session_read_committed() as db_sess:
            rows = await db_sess.scalars(
                sa.select(PermissionRow.operation)
                .join(UserRoleRow, UserRoleRow.role_id == PermissionRow.role_id)
                .join(SessionRow, sa.cast(SessionRow.id, sa.String) == PermissionRow.scope_id)
                .where(
                    UserRoleRow.user_id == user_id,
                    PermissionRow.scope_type == ScopeType.SESSION,
                    PermissionRow.scope_id == str(session_id),
                    PermissionRow.entity_type == EntityType.SESSION,
                    SessionRow.status.not_in(SESSION_SHARE_DEAD_STATUSES),
                )
            )
            return frozenset(rows.all())

    # ---- writes ---------------------------------------------------------

    async def upsert(
        self,
        session_id: uuid.UUID,
        invitee_id: uuid.UUID,
        level: SessionShareLevel,
    ) -> SessionShareData:
        """Grant the level's operations to the invitee, replacing an earlier level."""
        async with self._db.begin_session() as db_sess:
            role_id = await self._personal_role_id(db_sess, invitee_id)
            await self._delete_permissions(db_sess, session_id, role_ids=[role_id])
            db_sess.add_all([
                PermissionRow(
                    role_id=role_id,
                    scope_type=ScopeType.SESSION,
                    scope_id=str(session_id),
                    entity_type=EntityType.SESSION,
                    operation=operation,
                    permission=Permission.from_operation(operation),
                )
                for operation in sorted(level.operations())
            ])
            has_edge = await db_sess.scalar(
                sa.select(sa.literal(1)).where(*self._ref_edge_conds(session_id, invitee_id))
            )
            if has_edge is None:
                db_sess.add(
                    AssociationScopesEntitiesRow(
                        scope_type=ScopeType.USER,
                        scope_id=str(invitee_id),
                        entity_type=EntityType.SESSION,
                        entity_id=str(session_id),
                        relation_type=RelationType.REF,
                    )
                )
            await db_sess.flush()
            shares = await self._shares_of_session(db_sess, session_id)
        for share in shares:
            if share.user_id == invitee_id:
                return share
        raise SessionShareNotFound("The share was not recorded.")

    async def delete(self, session_id: uuid.UUID, user_id: uuid.UUID) -> None:
        async with self._db.begin_session() as db_sess:
            role_ids = (
                await db_sess.scalars(
                    sa.select(UserRoleRow.role_id).where(UserRoleRow.user_id == user_id)
                )
            ).all()
            deleted = await self._delete_permissions(db_sess, session_id, role_ids=role_ids)
            await db_sess.execute(
                sa.delete(AssociationScopesEntitiesRow).where(
                    *self._ref_edge_conds(session_id, user_id)
                )
            )
        if deleted == 0:
            raise SessionShareNotFound(f"Session {session_id} is not shared with user {user_id}.")

    async def purge_session(self, session_id: uuid.UUID) -> None:
        """Remove every share of the session (it ended)."""
        async with self._db.begin_session() as db_sess:
            await db_sess.execute(
                sa.delete(PermissionRow).where(
                    PermissionRow.scope_type == ScopeType.SESSION,
                    PermissionRow.scope_id == str(session_id),
                    PermissionRow.entity_type == EntityType.SESSION,
                    PermissionRow.operation.in_(SESSION_SHARE_OPERATIONS),
                )
            )
            await db_sess.execute(
                sa.delete(AssociationScopesEntitiesRow).where(
                    AssociationScopesEntitiesRow.scope_type == ScopeType.USER,
                    AssociationScopesEntitiesRow.entity_type == EntityType.SESSION,
                    AssociationScopesEntitiesRow.entity_id == str(session_id),
                    AssociationScopesEntitiesRow.relation_type == RelationType.REF,
                )
            )

    async def purge_dead(self) -> int:
        """Remove the shares of sessions that are no longer alive."""
        alive = sa.select(sa.cast(SessionRow.id, sa.String)).where(
            SessionRow.status.not_in(SESSION_SHARE_DEAD_STATUSES)
        )
        async with self._db.begin_session() as db_sess:
            result = await _execute_counted(
                db_sess,
                sa.delete(PermissionRow).where(
                    PermissionRow.scope_type == ScopeType.SESSION,
                    PermissionRow.entity_type == EntityType.SESSION,
                    PermissionRow.operation.in_(SESSION_SHARE_OPERATIONS),
                    PermissionRow.scope_id.not_in(alive),
                ),
            )
            await db_sess.execute(
                sa.delete(AssociationScopesEntitiesRow).where(
                    AssociationScopesEntitiesRow.scope_type == ScopeType.USER,
                    AssociationScopesEntitiesRow.entity_type == EntityType.SESSION,
                    AssociationScopesEntitiesRow.relation_type == RelationType.REF,
                    AssociationScopesEntitiesRow.entity_id.not_in(alive),
                )
            )
            return int(result.rowcount or 0)

    # ---- helpers --------------------------------------------------------

    @staticmethod
    def _ref_edge_conds(
        session_id: uuid.UUID, user_id: uuid.UUID
    ) -> tuple[sa.ColumnElement[bool], ...]:
        return (
            AssociationScopesEntitiesRow.scope_type == ScopeType.USER,
            AssociationScopesEntitiesRow.scope_id == str(user_id),
            AssociationScopesEntitiesRow.entity_type == EntityType.SESSION,
            AssociationScopesEntitiesRow.entity_id == str(session_id),
            AssociationScopesEntitiesRow.relation_type == RelationType.REF,
        )

    @staticmethod
    async def _personal_role_id(db_sess: SASession, user_id: uuid.UUID) -> uuid.UUID:
        """The user's own role: the one holding a permission scoped to the user."""
        role_id = await db_sess.scalar(
            sa.select(PermissionRow.role_id)
            .join(UserRoleRow, UserRoleRow.role_id == PermissionRow.role_id)
            .where(
                UserRoleRow.user_id == user_id,
                PermissionRow.scope_type == ScopeType.USER,
                PermissionRow.scope_id == str(user_id),
            )
            .limit(1)
        )
        if role_id is None:
            raise SessionShareInviteeHasNoRole(f"User {user_id} has no personal role.")
        return role_id

    @staticmethod
    async def _delete_permissions(
        db_sess: SASession,
        session_id: uuid.UUID,
        *,
        role_ids: Sequence[uuid.UUID],
    ) -> int:
        if not role_ids:
            return 0
        result = await _execute_counted(
            db_sess,
            sa.delete(PermissionRow).where(
                PermissionRow.role_id.in_(role_ids),
                PermissionRow.scope_type == ScopeType.SESSION,
                PermissionRow.scope_id == str(session_id),
                PermissionRow.entity_type == EntityType.SESSION,
                PermissionRow.operation.in_(SESSION_SHARE_OPERATIONS),
            ),
        )
        return int(result.rowcount or 0)

    @staticmethod
    async def _shares_of_session(
        db_sess: SASession, session_id: uuid.UUID
    ) -> list[SessionShareData]:
        rows = (
            await db_sess.execute(
                sa.select(
                    UserRow.uuid,
                    UserRow.email,
                    UserRow.username,
                    PermissionRow.operation,
                    PermissionRow.created_at,
                )
                .select_from(PermissionRow)
                .join(UserRoleRow, UserRoleRow.role_id == PermissionRow.role_id)
                .join(UserRow, UserRow.uuid == UserRoleRow.user_id)
                .where(
                    PermissionRow.scope_type == ScopeType.SESSION,
                    PermissionRow.scope_id == str(session_id),
                    PermissionRow.entity_type == EntityType.SESSION,
                    PermissionRow.operation.in_(SESSION_SHARE_OPERATIONS),
                )
            )
        ).all()
        ops: dict[uuid.UUID, set[OperationType]] = defaultdict(set)
        info: dict[uuid.UUID, tuple[str, str | None]] = {}
        granted: dict[uuid.UUID, datetime | None] = {}
        for row in rows:
            ops[row.uuid].add(row.operation)
            info[row.uuid] = (row.email, row.username)
            earlier = granted.get(row.uuid)
            granted[row.uuid] = row.created_at if earlier is None else min(earlier, row.created_at)
        return sorted(
            (
                SessionShareData(
                    session_id=session_id,
                    user_id=user_id,
                    email=info[user_id][0],
                    username=info[user_id][1],
                    level=SessionShareLevel.from_operations(frozenset(user_ops)),
                    created_at=granted[user_id],
                )
                for user_id, user_ops in ops.items()
            ),
            key=lambda share: share.email,
        )


async def _execute_counted(db_sess: SASession, statement: sa.Executable) -> CursorResult[Any]:
    """Execute a DML statement and keep its affected-row count."""
    return cast(CursorResult[Any], await db_sess.execute(statement))
