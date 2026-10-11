"""Errors of compute session sharing (BEP-1073)."""

from typing import override

from aiohttp import web

from ai.backend.common.exception import (
    BackendAIError,
    ErrorCode,
    ErrorDetail,
    ErrorDomain,
    ErrorOperation,
)
from ai.backend.manager.errors.common import ObjectNotFound


class SessionShareSessionNotFound(ObjectNotFound):
    """The session does not exist or is no longer alive."""

    object_name = "session"

    @override
    def error_code(self) -> ErrorCode:
        return ErrorCode(
            domain=ErrorDomain.SESSION,
            operation=ErrorOperation.READ,
            error_detail=ErrorDetail.NOT_FOUND,
        )


class SessionShareInviteeNotFound(ObjectNotFound):
    """No active user matches the invitee."""

    object_name = "user"

    @override
    def error_code(self) -> ErrorCode:
        return ErrorCode(
            domain=ErrorDomain.SESSION,
            operation=ErrorOperation.CREATE,
            error_detail=ErrorDetail.NOT_FOUND,
        )


class SessionShareNotFound(ObjectNotFound):
    """The session is not shared with that user."""

    object_name = "session-share"

    @override
    def error_code(self) -> ErrorCode:
        return ErrorCode(
            domain=ErrorDomain.SESSION,
            operation=ErrorOperation.HARD_DELETE,
            error_detail=ErrorDetail.NOT_FOUND,
        )


class SessionShareForbidden(BackendAIError, web.HTTPForbidden):
    """The requester may not manage the shares of the session."""

    error_type = "https://api.backend.ai/probs/session-share-forbidden"
    error_title = "Only the session owner, a project admin or a superadmin may manage its shares."

    @override
    def error_code(self) -> ErrorCode:
        return ErrorCode(
            domain=ErrorDomain.SESSION,
            operation=ErrorOperation.UPDATE,
            error_detail=ErrorDetail.FORBIDDEN,
        )


class SessionShareInvalidInvitee(BackendAIError, web.HTTPBadRequest):
    """The invitee is the owner or not a member of the session's project."""

    error_type = "https://api.backend.ai/probs/session-share-invalid-invitee"
    error_title = "The invitee must be another member of the session's project."

    @override
    def error_code(self) -> ErrorCode:
        return ErrorCode(
            domain=ErrorDomain.SESSION,
            operation=ErrorOperation.CREATE,
            error_detail=ErrorDetail.INVALID_PARAMETERS,
        )


class SessionShareInviteeHasNoRole(BackendAIError, web.HTTPConflict):
    """The invitee has no personal RBAC role to hold the share."""

    error_type = "https://api.backend.ai/probs/session-share-invitee-has-no-role"
    error_title = "The invitee has no personal RBAC role."

    @override
    def error_code(self) -> ErrorCode:
        return ErrorCode(
            domain=ErrorDomain.SESSION,
            operation=ErrorOperation.CREATE,
            error_detail=ErrorDetail.CONFLICT,
        )


class SessionShareAccessDenied(BackendAIError, web.HTTPForbidden):
    """The session is neither owned by nor shared with the requester for this operation."""

    error_type = "https://api.backend.ai/probs/session-share-access-denied"
    error_title = "The session is not shared with you for this operation."

    @override
    def error_code(self) -> ErrorCode:
        return ErrorCode(
            domain=ErrorDomain.SESSION,
            operation=ErrorOperation.ACCESS,
            error_detail=ErrorDetail.FORBIDDEN,
        )
