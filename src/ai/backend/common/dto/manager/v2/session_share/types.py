"""
Types for session share DTOs v2.
"""

from __future__ import annotations

from enum import StrEnum


class SessionShareLevelDTO(StrEnum):
    """What an invitee may do in a shared session."""

    APP = "app"
    EXECUTE = "execute"
