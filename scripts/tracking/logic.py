"""Pure rules for tracking work in GitHub issues and projects. No network, no GitHub calls."""

from __future__ import annotations

import yaml

IN_PROGRESS = "In progress"
IN_REVIEW = "In review"
DONE = "Done"


def parse_tracking(text: str) -> list[str]:
    """Project refs ("org/name") from a repo's .github/tracking.yml text.

    Anything unusable (empty, malformed, wrong shape) means "not tracked", never an error.
    """
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return []
    if not isinstance(data, dict):
        return []
    projects = data.get("projects")
    if not isinstance(projects, list) or not all(isinstance(p, str) and p for p in projects):
        return []
    return list(projects)


def projects_to_add(repo_projects: list[str], already_in: set[str]) -> list[str]:
    """Projects an issue should join: those its repo lists that it is not already in."""
    return [p for p in repo_projects if p not in already_in]


def rollup_status(child_statuses: list[str | None], closed: list[bool] | None = None) -> str | None:
    """Derived status of a parent from its children, or None for "leave it alone".

    A child with no project status (None, for example in an untracked repo) counts as Done when its
    issue is closed (`closed[i]`), otherwise as not started. Archived children keep their status, so
    they count as before.
    """
    if not child_statuses:
        return None
    statuses = [
        (DONE if closed and closed[i] else None) if s is None else s
        for i, s in enumerate(child_statuses)
    ]
    if any(s == IN_PROGRESS for s in statuses):
        return IN_PROGRESS
    if all(s == DONE for s in statuses):
        return DONE
    open_children = [s for s in statuses if s != DONE]
    if all(s == IN_REVIEW for s in open_children):
        return IN_REVIEW
    return None
