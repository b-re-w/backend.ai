"""Route registration for REST v2 session share endpoints (BEP-1073)."""

from __future__ import annotations

from ai.backend.manager.api.rest.middleware.auth import auth_required
from ai.backend.manager.api.rest.routing import RouteRegistry

from .handler import V2SessionShareHandler


def add_v2_session_share_routes(
    sessions: RouteRegistry,
    handler: V2SessionShareHandler,
) -> RouteRegistry:
    """Add the share sub-resource to the v2 ``sessions`` registry."""
    sessions.add("POST", "/{session_id}/shares", handler.create, middlewares=[auth_required])
    sessions.add("POST", "/{session_id}/shares/search", handler.search, middlewares=[auth_required])
    sessions.add(
        "DELETE", "/{session_id}/shares/{user_id}", handler.delete, middlewares=[auth_required]
    )
    return sessions
