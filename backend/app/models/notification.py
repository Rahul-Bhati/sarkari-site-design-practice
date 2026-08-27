from dataclasses import dataclass, field
from typing import Any


@dataclass
class DigestGroup:
    category: str
    entries: list[dict[str, Any]]


@dataclass
class Digest:
    """What generate_digest() returns for one subscriber."""

    subscriber_id: str
    email: str | None
    phone: str | None
    frequency: str
    groups: list[DigestGroup] = field(default_factory=list)
    unsubscribe_token: str = ""

    @property
    def entry_ids(self) -> list[str]:
        return [e["id"] for g in self.groups for e in g.entries]

    @property
    def total(self) -> int:
        return sum(len(g.entries) for g in self.groups)

    @property
    def states(self) -> set[str]:
        return {e["state"] for g in self.groups for e in g.entries}
