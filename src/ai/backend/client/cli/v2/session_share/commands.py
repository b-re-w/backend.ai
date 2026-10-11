"""CLI commands for v2 compute session sharing (BEP-1073)."""

from __future__ import annotations

import asyncio

import click

from ai.backend.client.cli.v2.helpers import create_v2_registry, load_v2_config, print_result


@click.group(name="session-share")
def session_share() -> None:
    """Share a running session with members of its project."""


@session_share.command()
@click.argument("session_id")
@click.option("--user-id", default=None, help="Invitee user ID.")
@click.option("--email", default=None, help="Invitee email address.")
@click.option(
    "--level",
    type=click.Choice(["app", "execute"]),
    default="app",
    show_default=True,
    help="'app': view the session and open its apps; 'execute': also use the execute API.",
)
def create(session_id: str, user_id: str | None, email: str | None, level: str) -> None:
    """Share SESSION_ID with a user (or change the user's level)."""
    from uuid import UUID

    from ai.backend.common.dto.manager.v2.session_share.request import CreateSessionShareInput
    from ai.backend.common.dto.manager.v2.session_share.types import SessionShareLevelDTO

    async def _run() -> None:
        registry = await create_v2_registry(load_v2_config())
        try:
            result = await registry.session_share.create(
                UUID(session_id),
                CreateSessionShareInput(
                    user_id=UUID(user_id) if user_id else None,
                    email=email,
                    level=SessionShareLevelDTO(level),
                ),
            )
            print_result(result)
        finally:
            await registry.close()

    asyncio.run(_run())


@session_share.command()
@click.argument("session_id")
@click.option("--limit", default=50, type=int, show_default=True, help="Max results per page.")
@click.option("--offset", default=0, type=int, show_default=True, help="Pagination offset.")
def search(session_id: str, limit: int, offset: int) -> None:
    """List the users SESSION_ID is shared with."""
    from uuid import UUID

    from ai.backend.common.dto.manager.v2.session_share.request import SearchSessionSharesInput

    async def _run() -> None:
        registry = await create_v2_registry(load_v2_config())
        try:
            result = await registry.session_share.search(
                UUID(session_id),
                SearchSessionSharesInput(limit=limit, offset=offset),
            )
            print_result(result)
        finally:
            await registry.close()

    asyncio.run(_run())


@session_share.command()
@click.argument("session_id")
@click.argument("user_id")
def delete(session_id: str, user_id: str) -> None:
    """Revoke USER_ID's access to SESSION_ID."""
    from uuid import UUID

    async def _run() -> None:
        registry = await create_v2_registry(load_v2_config())
        try:
            result = await registry.session_share.delete(UUID(session_id), UUID(user_id))
            print_result(result)
        finally:
            await registry.close()

    asyncio.run(_run())
