"""Repository for compute session sharing (BEP-1073)."""

from __future__ import annotations

import uuid

from ai.backend.common.data.permission.types import OperationType
from ai.backend.common.exception import BackendAIError
from ai.backend.common.metrics.metric import DomainType, LayerType
from ai.backend.common.resilience.policies.metrics import MetricArgs, MetricPolicy
from ai.backend.common.resilience.policies.retry import BackoffStrategy, RetryArgs, RetryPolicy
from ai.backend.common.resilience.resilience import Resilience
from ai.backend.manager.data.session_share.types import (
    SessionShareData,
    SessionShareLevel,
    SessionShareListResult,
    SessionShareTarget,
)
from ai.backend.manager.models.utils import ExtendedAsyncSAEngine
from ai.backend.manager.repositories.session_share.db_source.db_source import SessionShareDBSource

session_share_repository_resilience = Resilience(
    policies=[
        MetricPolicy(
            MetricArgs(domain=DomainType.REPOSITORY, layer=LayerType.SESSION_SHARE_REPOSITORY)
        ),
        RetryPolicy(
            RetryArgs(
                max_retries=10,
                retry_delay=0.1,
                backoff_strategy=BackoffStrategy.FIXED,
                non_retryable_exceptions=(BackendAIError,),
            )
        ),
    ]
)


class SessionShareRepository:
    """Repository layer that delegates to the data source."""

    _db_source: SessionShareDBSource

    def __init__(self, db: ExtendedAsyncSAEngine) -> None:
        self._db_source = SessionShareDBSource(db)

    @session_share_repository_resilience.apply()
    async def get_target(self, session_id: uuid.UUID) -> SessionShareTarget:
        return await self._db_source.get_target(session_id)

    @session_share_repository_resilience.apply()
    async def is_project_session_admin(self, user_id: uuid.UUID, project_id: uuid.UUID) -> bool:
        return await self._db_source.is_project_session_admin(user_id, project_id)

    @session_share_repository_resilience.apply()
    async def resolve_invitee(self, user_id: uuid.UUID | None, email: str | None) -> uuid.UUID:
        return await self._db_source.resolve_invitee(user_id, email)

    @session_share_repository_resilience.apply()
    async def is_project_member(self, user_id: uuid.UUID, project_id: uuid.UUID) -> bool:
        return await self._db_source.is_project_member(user_id, project_id)

    @session_share_repository_resilience.apply()
    async def search(
        self, session_id: uuid.UUID, limit: int, offset: int
    ) -> SessionShareListResult:
        return await self._db_source.search(session_id, limit, offset)

    @session_share_repository_resilience.apply()
    async def shared_operations(
        self, user_id: uuid.UUID, session_id: uuid.UUID
    ) -> frozenset[OperationType]:
        return await self._db_source.shared_operations(user_id, session_id)

    @session_share_repository_resilience.apply()
    async def upsert(
        self, session_id: uuid.UUID, invitee_id: uuid.UUID, level: SessionShareLevel
    ) -> SessionShareData:
        return await self._db_source.upsert(session_id, invitee_id, level)

    @session_share_repository_resilience.apply()
    async def delete(self, session_id: uuid.UUID, user_id: uuid.UUID) -> None:
        await self._db_source.delete(session_id, user_id)

    @session_share_repository_resilience.apply()
    async def purge_session(self, session_id: uuid.UUID) -> None:
        await self._db_source.purge_session(session_id)

    @session_share_repository_resilience.apply()
    async def purge_dead(self) -> int:
        return await self._db_source.purge_dead()
