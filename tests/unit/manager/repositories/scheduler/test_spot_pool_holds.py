"""Spot kernels hold no cpu/mem on ``agent_resources`` (shared pool).

These tests drive the hold primitives of ``ScheduleDBSource`` with a recording
fake session, so they need no database. The statements are inspected through
their compiled SQL.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from ai.backend.common.types import AgentId, KernelId, ResourceSlot
from ai.backend.manager.repositories.scheduler.db_source.db_source import (
    ScheduleDBSource,
    _held_amount,
)

SUFFIX = "-spot.shares"
KERNEL = KernelId(uuid.uuid4())
AGENT = AgentId("a1")


def _sql(stmt: Any) -> str:
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


class _Result:
    def __init__(self, rows: list[Any], rowcount: int = 1) -> None:
        self._rows = rows
        self.rowcount = rowcount

    def all(self) -> list[Any]:
        return self._rows

    def first(self) -> Any:
        return self._rows[0] if self._rows else None


class _FakeSession:
    """Answers the allocation-row SELECT and records every UPDATE."""

    def __init__(self, requested: dict[str, str]) -> None:
        self._requested = requested
        self.updates: list[str] = []

    async def execute(self, stmt: Any) -> _Result:
        sql = _sql(stmt)
        if sql.lstrip().upper().startswith("SELECT"):
            return _Result([
                SimpleNamespace(slot_name=k, requested=Decimal(v))
                for k, v in sorted(self._requested.items())
            ])
        self.updates.append(sql)
        if "UPDATE resource_allocations" in sql and "RETURNING" in sql:
            return _Result([SimpleNamespace(reserved=Decimal(1), slot_name="x", prereserved=1)])
        return _Result([])


def _agent_updates(sess: _FakeSession) -> list[str]:
    return [s for s in sess.updates if s.startswith("UPDATE agent_resources")]


SPOT_REQ = {"cpu": "4", "mem": "1024", "pro6000-spot.shares": "1"}
OWNER_REQ = {"cpu": "4", "mem": "1024", "pro6000.shares": "1"}


def _source(suffix: str) -> ScheduleDBSource:
    return ScheduleDBSource(MagicMock(), suffix)


async def test_skip_set_for_spot_only_when_enabled() -> None:
    assert await _source(SUFFIX)._pooled_slots_to_skip(_FakeSession(SPOT_REQ), KERNEL) == {
        "cpu",
        "mem",
    }
    assert await _source(SUFFIX)._pooled_slots_to_skip(_FakeSession(OWNER_REQ), KERNEL) == set()
    assert await _source("")._pooled_slots_to_skip(_FakeSession(SPOT_REQ), KERNEL) == set()


async def test_reserve_skips_cpu_mem_for_spot() -> None:
    sess = _FakeSession(SPOT_REQ)
    await _source(SUFFIX)._reserve_kernel_resources(sess, KERNEL, AGENT)  # type: ignore[arg-type]
    agent_updates = _agent_updates(sess)
    assert len(agent_updates) == 1
    assert "pro6000-spot.shares" in agent_updates[0]
    assert "'cpu'" not in agent_updates[0] and "'mem'" not in agent_updates[0]
    # The allocation rows are stamped with a zero hold for cpu/mem.
    stamp = next(s for s in sess.updates if s.startswith("UPDATE resource_allocations"))
    assert "CASE WHEN" in stamp and "'cpu'" in stamp


async def test_reserve_books_everything_for_owner_and_when_disabled() -> None:
    for suffix, req in ((SUFFIX, OWNER_REQ), ("", SPOT_REQ)):
        sess = _FakeSession(req)
        await _source(suffix)._reserve_kernel_resources(sess, KERNEL, AGENT)  # type: ignore[arg-type]
        assert len(_agent_updates(sess)) == 3
        stamp = next(s for s in sess.updates if s.startswith("UPDATE resource_allocations"))
        assert "CASE WHEN" not in stamp


async def test_allocate_skips_cpu_mem_for_spot() -> None:
    sess = _FakeSession(SPOT_REQ)
    occupied = ResourceSlot({"cpu": "4", "mem": "1024", "pro6000-spot.shares": "1"})
    await _source(SUFFIX)._allocate_kernel_resources(sess, KERNEL, AGENT, occupied)  # type: ignore[arg-type]
    agent_updates = _agent_updates(sess)
    assert len(agent_updates) == 1
    assert "pro6000-spot.shares" in agent_updates[0]


async def test_allocate_moves_all_slots_for_owner() -> None:
    sess = _FakeSession(OWNER_REQ)
    occupied = ResourceSlot({"cpu": "4", "mem": "1024", "pro6000.shares": "1"})
    await _source(SUFFIX)._allocate_kernel_resources(sess, KERNEL, AGENT, occupied)  # type: ignore[arg-type]
    assert len(_agent_updates(sess)) == 3


async def test_prereserve_stamps_zero_for_spot_cpu_mem() -> None:
    sess = _FakeSession(SPOT_REQ)
    await _source(SUFFIX)._prereserve_kernel_resources(sess, KERNEL, AGENT)  # type: ignore[arg-type]
    stamp = next(s for s in sess.updates if s.startswith("UPDATE resource_allocations"))
    assert "SET prereserved=CASE WHEN" in stamp and "'cpu'" in stamp


def test_held_amount_expression() -> None:
    assert "CASE" not in _sql(sa.select(_held_amount(frozenset())))
    case_sql = _sql(sa.select(_held_amount(frozenset({"cpu", "mem"}))))
    assert "CASE WHEN" in case_sql and "'cpu'" in case_sql and "'mem'" in case_sql
