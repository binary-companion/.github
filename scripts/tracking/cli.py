"""Tracking commands: add to projects, PR status moves, parent roll-up, failed-CI bug.

The run_* functions take the GitHub layer as `api` so tests can fake it. main() wires the real one.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from logic import DONE, IN_PROGRESS, IN_REVIEW, parse_tracking, projects_to_add, rollup_status  # noqa: E402

PR_STATUS = {"in_review": IN_REVIEW, "done": DONE}


def run_add(api, repo: str, number: int, tracking_text: str) -> None:
    refs = parse_tracking(tracking_text)
    if not refs:
        return
    issue = api.issue(repo, number)
    joined = {i.project_id for i in issue.items}
    already = {r for r in refs if api.resolve_project(r).id in joined}
    for ref in projects_to_add(refs, already):
        api.add_to_project(api.resolve_project(ref), issue)


def run_pr(api, repo: str, pr_number: int, target: str) -> None:
    status = PR_STATUS[target]
    for irepo, inum in api.closing_issues(repo, pr_number):
        issue = api.issue(irepo, inum)
        for item in issue.items:
            api.set_status(item, status)
        run_rollup(api, irepo, inum)


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
                mine = kid.item_in(item.project_id)
                statuses.append(updated.get((kid.repo, kid.number, item.project_id)) or (mine.status if mine else None))
            new = rollup_status(statuses, [k.closed for k in kids])
            if new is None and item.status == DONE and any(s != DONE for s in statuses):
                new = IN_PROGRESS  # a child was reopened
            if new and new != item.status:
                api.set_status(item, new)
                updated[(parent.repo, parent.number, item.project_id)] = new
        cur = parent


def run_sweep(api, repo: str) -> None:
    """Safety net for hand-set statuses, which fire no event: roll up from every open child in the repo."""
    for number in api.open_children(repo):
        run_rollup(api, repo, number)


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
    for name in ("add", "rollup"):
        s = sub.add_parser(name)
        s.add_argument("--repo", required=True)
        s.add_argument("--issue", type=int, required=True)
        if name == "add":
            s.add_argument("--tracking-file", required=True)
    s = sub.add_parser("sweep")
    s.add_argument("--repo", required=True)
    s = sub.add_parser("pr")
    s.add_argument("--repo", required=True)
    s.add_argument("--pr", type=int, required=True)
    s.add_argument("--target", choices=sorted(PR_STATUS), required=True)
    s = sub.add_parser("ci-bug")
    s.add_argument("--repo", required=True)
    s.add_argument("--sha", required=True)
    s.add_argument("--run-url", required=True)
    s.add_argument("--pr", type=int)
    a = p.parse_args(argv)
    api = GH()
    if a.cmd == "add":
        path = Path(a.tracking_file)
        run_add(api, a.repo, a.issue, path.read_text() if path.exists() else "")
    elif a.cmd == "pr":
        run_pr(api, a.repo, a.pr, a.target)
    elif a.cmd == "rollup":
        run_rollup(api, a.repo, a.issue)
    elif a.cmd == "sweep":
        run_sweep(api, a.repo)
    else:
        run_ci_bug(api, a.repo, a.sha, a.run_url, a.pr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
