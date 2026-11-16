"""Plain data the tracking commands pass between the GitHub layer and the rules."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Project:
    id: str    # GraphQL node id
    ref: str   # "org/title", as written in tracking.yml


@dataclass
class Item:
    item_id: str
    project_id: str
    status: str | None


@dataclass
class Issue:
    id: str          # GraphQL node id
    repo: str        # "owner/name"
    number: int
    closed: bool = False
    parent: tuple[str, int] | None = None   # (repo, number)
    items: list[Item] = field(default_factory=list)

    def item_in(self, project_id: str) -> Item | None:
        return next((i for i in self.items if i.project_id == project_id), None)
