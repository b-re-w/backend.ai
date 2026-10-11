from typing import override

from ai.backend.manager.actions.monitors.monitor import ActionMonitor
from ai.backend.manager.actions.processor import ActionProcessor
from ai.backend.manager.actions.types import AbstractProcessorPackage, ActionSpec
from ai.backend.manager.actions.validators import ActionValidators
from ai.backend.manager.services.session_share.actions.create import (
    CreateSessionShareAction,
    CreateSessionShareActionResult,
)
from ai.backend.manager.services.session_share.actions.delete import (
    DeleteSessionShareAction,
    DeleteSessionShareActionResult,
)
from ai.backend.manager.services.session_share.actions.search import (
    SearchSessionSharesAction,
    SearchSessionSharesActionResult,
)
from ai.backend.manager.services.session_share.service import SessionShareService


class SessionShareProcessors(AbstractProcessorPackage):
    create: ActionProcessor[CreateSessionShareAction, CreateSessionShareActionResult]
    delete: ActionProcessor[DeleteSessionShareAction, DeleteSessionShareActionResult]
    search: ActionProcessor[SearchSessionSharesAction, SearchSessionSharesActionResult]

    def __init__(
        self,
        service: SessionShareService,
        action_monitors: list[ActionMonitor],
        validators: ActionValidators,
    ) -> None:
        self.create = ActionProcessor(service.create, action_monitors)
        self.delete = ActionProcessor(service.delete, action_monitors)
        self.search = ActionProcessor(service.search, action_monitors)

    @override
    def supported_actions(self) -> list[ActionSpec]:
        return [
            CreateSessionShareAction.spec(),
            DeleteSessionShareAction.spec(),
            SearchSessionSharesAction.spec(),
        ]
