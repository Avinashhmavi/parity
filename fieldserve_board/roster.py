"""The people: lookups and the rules that depend on who they are."""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from .models import Agent

COORDINATOR = "coordinator"
MANAGER = "manager"
ENGINEER = "engineer"
FINANCE = "finance"
UNKNOWN_ENGINEER_PREFIX = "#"


def _norm(name: str) -> str:
    return " ".join((name or "").split()).casefold()


class Roster:
    """Roster of agents with the lookups the workflow needs.

    Name matching is case-insensitive and whitespace-tolerant, because the
    ticket's ``manager`` field is free text and humans type names in a sheet.
    The canonical spelling always comes from the roster.
    """

    def __init__(self, agents: Iterable[Agent]):
        self.agents: List[Agent] = list(agents)
        self.by_id: Dict[int, Agent] = {a.id: a for a in self.agents}
        self._by_role: Dict[str, List[Agent]] = {}
        for agent in self.agents:
            self._by_role.setdefault(_norm(agent.role), []).append(agent)
        self._by_name: Dict[str, List[Agent]] = {}
        for agent in self.agents:
            self._by_name.setdefault(_norm(agent.name), []).append(agent)

    @classmethod
    def from_sheet_rows(cls, rows: Iterable[dict]) -> Roster:
        """Rebuild a roster from the Roster sheet (used when no API is at hand)."""
        return cls(
            Agent(int(r["ID"]), r["Name"].strip(), r.get("Role", "").strip(), r.get("Team", "").strip())
            for r in rows
            if str(r.get("ID", "")).strip().isdigit() and str(r.get("Name", "")).strip()
        )

    def with_role(self, role: str) -> List[Agent]:
        return sorted(self._by_role.get(_norm(role), []), key=lambda a: a.name)

    @property
    def engineers(self) -> List[Agent]:
        return self.with_role(ENGINEER)

    @property
    def managers(self) -> List[Agent]:
        return self.with_role(MANAGER)

    def find(self, name: str, role: Optional[str] = None) -> Optional[Agent]:
        """Find an agent by name, optionally restricted to a role."""
        matches = self._by_name.get(_norm(name), [])
        if role is not None:
            matches = [a for a in matches if _norm(a.role) == _norm(role)]
        return matches[0] if matches else None

    def canonical_manager(self, name: str) -> str:
        """Roster spelling of a manager name, or the trimmed input if unknown."""
        agent = self.find(name, MANAGER)
        return agent.name if agent else " ".join((name or "").split())

    def engineer_name(self, engineer_id: Optional[int]) -> str:
        """Sheet label for an ``engineer_id``.

        An id that is not on the roster still counts as "assigned" (the API
        said so), so it is shown as ``#<id>`` rather than hidden as blank.
        """
        if engineer_id is None:
            return ""
        agent = self.by_id.get(engineer_id)
        return agent.name if agent else f"{UNKNOWN_ENGINEER_PREFIX}{engineer_id}"

    def coordinator_for(self, ticket_id: int) -> str:
        """``coordinators_sorted_by_name[ticket_id % 2]`` from the brief."""
        coordinators = self.with_role(COORDINATOR)
        if not coordinators:
            return ""
        return coordinators[ticket_id % 2 if len(coordinators) >= 2 else 0].name

    def finance_owner(self) -> str:
        finance = self.with_role(FINANCE)
        return finance[0].name if finance else ""

    def to_rows(self) -> List[dict]:
        return [
            {
                "id": a.id,
                "name": a.name,
                "role": a.role,
                "team": a.team,
                "reports_to": a.reports_to,
            }
            for a in sorted(self.agents, key=lambda a: (_norm(a.role), a.name))
        ]
