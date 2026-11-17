"""Tracking commands: the organization sweep (add to projects, parent roll-up, failed-CI bug) and the PR issue check.

The run_* functions take the GitHub layer as `api` so tests can fake it. main() wires the real one.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from logic import DONE, IN_PROGRESS, parse_tracking, projects_to_add, rollup_status  # noqa: E402

BOT_AUTHORS = {"timetug-bot"}
# "#12" or "owner/repo#12", not glued to a word or a URL fragment.
ISSUE_REF = re.compile(r"(?<![\w/#&-])(?:[\w.-]+/[\w.-]+)?#\d+\b")


def run_add(api, repo: str, number: int, tracking_text: str) -> None:
    refs = parse_tracking(tracking_text)
    if not refs:
        return
    issue = api.issue(repo, number)
    joined = {i.project_id for i in issue.items}
    already = {r for r in refs if api.resolve_project(r).id in joined}
    for ref in projects_to_add(refs, already):
        api.add_to_project(api.resolve_project(ref), issue)


def run_pr_check(api, repo: str, pr_number: int, body: str, author: str) -> tuple[bool, str]:
    """A pull request that is part of a story must be linked to it. One that mentions no issue is fine.

    GitHub links a pull request to an issue only through a closing keyword (Fixes, Closes, Resolves);
    "Part of #N" is just a mention and does not show the pull request on the issue.
    """
    if author.endswith("[bot]") or author in BOT_AUTHORS:
        return True, ""
    if api.closing_issues(repo, pr_number) or not ISSUE_REF.search(body or ""):
        return True, ""
    return False, (
        "This pull request mentions an issue but is not linked to it, so it will not show on the issue. "
        "GitHub links only with a closing keyword: use `Fixes #N` (another repository: `Fixes owner/repo#N`). "
        "If the issue is bigger than this pull request, file a sub-issue for this pull request in this "
        "repository and use `Fixes` on that one."
    )


def run_rollup(api, repo: str, number: int) -> None:
    """Set each ancestor's status from its children, walking up. Parent status is derived, never hand-set."""
    updated: dict[tuple[str, int, str], str] = {}
    cur = api.issue(repo, number)
    while cur.parent:
        parent = api.issue(*cur.parent)
        kids = api.sub_issues(parent.repo, parent.number)
        for item in parent.items:
            statuses = []
            for kid in kids:
                mine = kid.item_in(item.project_id) or next((i for i in kid.items if i.status), None)
                statuses.append(updated.get((kid.repo, kid.number, item.project_id)) or (mine.status if mine else None))
            new = rollup_status(statuses, [k.closed for k in kids])
            if new is None and item.status == DONE and any(s != DONE for s in statuses):
                new = IN_PROGRESS  # a child was reopened
            if new and new != item.status:
                api.set_status(item, new)
                updated[(parent.repo, parent.number, item.project_id)] = new
        cur = parent


def run_sweep_all(api) -> list[tuple[str, Exception]]:
    """Every tracked repository: add open issues to its projects, roll parents up, file a CI bug.

    One repository failing does not stop the others; the failures are returned for the caller to report.
    """
    failures: list[tuple[str, Exception]] = []
    for repo, tracking_text in api.tracked_repos().items():
        if not parse_tracking(tracking_text):
            continue
        try:
            for number, closed, has_parent in api.scan(repo):
                if not closed:
                    run_add(api, repo, number, tracking_text)
                if has_parent:
                    run_rollup(api, repo, number)
            failure = api.latest_failure(repo)
            if failure:
                sha, run_url, pr_number = failure
                if not api.bug_exists(repo, sha):
                    run_ci_bug(api, repo, sha, run_url, pr_number)
        except Exception as error:  # noqa: BLE001 - isolate each repository
            failures.append((repo, error))
    return failures


def run_ci_bug(api, repo: str, sha: str, run_url: str, pr_number: int | None) -> int:
    ref = f" (merged in #{pr_number})" if pr_number else ""
    title = f"CI failed on master after {sha[:7]}"
    body = (
        f"CI failed on the default branch after commit {sha}{ref}.\n\n"
        f"- Run: {run_url}\n\n"
        "## Success criteria\n- [ ] The cause is found and fixed\n- [ ] CI is green on the default branch\n\n"
        "Filed automatically. The issue that caused it stays Done; track the fix here."
    )
    return api.create_bug(repo, title, body)


def main(argv: list[str] | None = None) -> int:
    from gh_api import GH

    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sweep-all")
    s = sub.add_parser("pr-check")
    s.add_argument("--repo", required=True)
    s.add_argument("--pr", type=int, required=True)
    s.add_argument("--body", default="")
    s.add_argument("--author", required=True)
    a = p.parse_args(argv)
    api = GH()
    if a.cmd == "pr-check":
        ok, message = run_pr_check(api, a.repo, a.pr, a.body, a.author)
        if not ok:
            print(f"::error::{message}")
            return 1
    else:
        failures = run_sweep_all(api)
        for repo, error in failures:
            print(f"::error::{repo}: {error}")
        return 1 if failures else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
