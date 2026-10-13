"""
Terminating a kernel while create_kernel() still waits for its runner must not deadlock the
agent: the clean handler cancels that wait while holding registry_lock.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ai.backend.agent.docker.agent import DockerAgent
from ai.backend.agent.docker.kernel import DockerCodeRunner
from ai.backend.common.events.event_types.kernel.anycast import KernelTerminatedAnycastEvent
from ai.backend.common.events.event_types.kernel.types import KernelLifecycleEventReason
from ai.backend.common.types import KernelId, SessionId


@pytest.fixture
def runner() -> Iterator[DockerCodeRunner]:
    """A runner whose status request is never answered, like one whose container is gone."""
    sockets = MagicMock()
    sockets.send_multipart = AsyncMock()
    with patch.object(DockerCodeRunner, "_get_socket_pair", AsyncMock(return_value=sockets)):
        runner = DockerCodeRunner.__new__(DockerCodeRunner)
        runner.status_queue = asyncio.Queue()
        yield runner


@pytest.fixture
def save_last_registry() -> Iterator[AsyncMock]:
    save = AsyncMock()
    with patch.object(DockerAgent, "save_last_registry", save):
        yield save


def _agent_with_pending_creation(kernel_id: KernelId, task: asyncio.Task[None]) -> DockerAgent:
    agent = DockerAgent.__new__(DockerAgent)
    agent.local_config = MagicMock()
    agent.local_config.debug.log_events = False
    agent._pending_creation_tasks = {kernel_id: {task}}
    return agent


def _terminated(kernel_id: KernelId) -> KernelTerminatedAnycastEvent:
    return KernelTerminatedAnycastEvent(
        kernel_id, SessionId(uuid.uuid4()), reason=KernelLifecycleEventReason.USER_REQUESTED
    )


class TestStatusPollCancellation:
    async def test_cancelling_the_status_poll_propagates(self, runner: DockerCodeRunner) -> None:
        task = asyncio.create_task(runner.feed_and_get_status())
        await asyncio.sleep(0)

        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)


class TestPendingCreationOnTermination:
    async def test_creation_waiting_for_its_runner_stops_on_termination(
        self, runner: DockerCodeRunner, save_last_registry: AsyncMock
    ) -> None:
        kernel_id = KernelId(uuid.uuid4())

        async def create_kernel() -> None:
            # The init wait of create_kernel(), which turns the cancellation into its own error.
            try:
                await runner.feed_and_get_status()
            except asyncio.CancelledError as e:
                raise RuntimeError("container startup cancelled") from e

        task = asyncio.create_task(create_kernel())
        await asyncio.sleep(0)
        agent = _agent_with_pending_creation(kernel_id, task)

        await asyncio.wait_for(agent._pre_anycast_event(_terminated(kernel_id)), timeout=2)

        assert task.done()
        with pytest.raises(RuntimeError):
            task.result()
        save_last_registry.assert_awaited_once()

    async def test_a_creation_task_that_ignores_cancellation_cannot_block_termination(
        self, save_last_registry: AsyncMock
    ) -> None:
        kernel_id = KernelId(uuid.uuid4())
        release = asyncio.Event()

        async def stubborn() -> None:
            while not release.is_set():
                try:
                    await asyncio.sleep(3600)
                except asyncio.CancelledError:
                    continue

        task = asyncio.create_task(stubborn())
        await asyncio.sleep(0)
        agent = _agent_with_pending_creation(kernel_id, task)

        with patch("ai.backend.agent.agent.PENDING_CREATION_CANCEL_TIMEOUT", 0.1):
            await asyncio.wait_for(agent._pre_anycast_event(_terminated(kernel_id)), timeout=2)

        save_last_registry.assert_awaited_once()
        release.set()
        task.cancel()
        await asyncio.wait({task}, timeout=1)
