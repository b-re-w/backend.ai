from dataclasses import dataclass
from typing import Self

from ai.backend.manager.repositories.session_share.repository import SessionShareRepository
from ai.backend.manager.repositories.types import RepositoryArgs


@dataclass
class SessionShareRepositories:
    repository: SessionShareRepository

    @classmethod
    def create(cls, args: RepositoryArgs) -> Self:
        return cls(repository=SessionShareRepository(db=args.db))
