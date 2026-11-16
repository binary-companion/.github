import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cli import run_add, run_ci_bug, run_pr, run_rollup  # noqa: E402
from model import Issue, Item, Project  # noqa: E402

TT = Project("P_TT", "binary-companion/timetug")
LIB = Project("P_LIB", "binary-companion/libraries")


class FakeAPI:
    def __init__(self, issues=(), children=None, closing=None, projects=(TT, LIB)):
        self.issues = {(i.repo, i.number): i for i in issues}
        self.children = children or {}
        self.closing = closing or {}
        self.projects = {p.ref: p for p in projects}
        self.added = []
        self.status_writes = []
        self.bugs = []
        self.open_with_parent = {}

    def resolve_project(self, ref):
        return self.projects[ref]

    def issue(self, repo, number):
        return self.issues[(repo, number)]

    def sub_issues(self, repo, number):
        return [self.issues[k] for k in self.children.get((repo, number), [])]

    def add_to_project(self, project, issue):
        self.added.append((project.id, issue.number))
        item = Item(f"I_{project.id}_{issue.number}", project.id, "Backlog")
        issue.items.append(item)
        return item

    def set_status(self, item, status):
        self.status_writes.append((item.item_id, status))
        item.status = status

    def closing_issues(self, repo, pr):
        return self.closing.get((repo, pr), [])

    def open_children(self, repo):
        return self.open_with_parent.get(repo, [])

    def create_bug(self, repo, title, body):
        self.bugs.append((repo, title, body))
        return 99


def issue(repo, n, status=None, project=TT, closed=False, parent=None, items=None):
    its = items if items is not None else ([Item(f"I_{project.id}_{n}", project.id, status)] if status else [])
    return Issue(f"N{n}", repo, n, closed=closed, parent=parent, items=its)


def test_add_joins_each_listed_project_it_is_not_in():
    i = issue("o/a", 1, items=[Item("x", TT.id, "Backlog")])
    api = FakeAPI([i])
    run_add(api, "o/a", 1, "projects: [binary-companion/timetug, binary-companion/libraries]")
    assert api.added == [("P_LIB", 1)]


def test_add_untracked_repo_does_nothing():
    api = FakeAPI([issue("o/web", 1)])
    run_add(api, "o/web", 1, "")
    assert api.added == []


def test_pr_in_review_sets_every_project_item_of_each_closed_issue():
    i = issue("o/a", 1, items=[Item("a", TT.id, "In progress"), Item("b", LIB.id, "In progress")])
    api = FakeAPI([i], closing={("o/a", 7): [("o/a", 1)]})
    run_pr(api, "o/a", 7, "in_review")
    assert sorted(api.status_writes) == [("a", "In review"), ("b", "In review")]


def test_pr_merged_sets_done():
    i = issue("o/a", 1, "In review")
    api = FakeAPI([i], closing={("o/a", 7): [("o/a", 1)]})
    run_pr(api, "o/a", 7, "done")
    assert api.status_writes == [("I_P_TT_1", "Done")]


def test_pr_without_closing_issues_is_a_no_op():
    api = FakeAPI([])
    run_pr(api, "o/a", 7, "done")
    assert api.status_writes == []


def test_pr_handles_several_issues():
    api = FakeAPI([issue("o/a", 1, "In review"), issue("o/a", 2, "In review")],
                  closing={("o/a", 7): [("o/a", 1), ("o/a", 2)]})
    run_pr(api, "o/a", 7, "done")
    assert [w[1] for w in api.status_writes] == ["Done", "Done"]


def test_rollup_sets_parent_from_children_in_the_parents_project():
    parent = issue("o/a", 1, "Ready")
    c1 = issue("o/a", 2, "In progress", parent=("o/a", 1))
    c2 = issue("o/a", 3, "Backlog", parent=("o/a", 1))
    api = FakeAPI([parent, c1, c2], children={("o/a", 1): [("o/a", 2), ("o/a", 3)]})
    run_rollup(api, "o/a", 2)
    assert api.status_writes == [("I_P_TT_1", "In progress")]


def test_rollup_without_parent_is_a_no_op():
    api = FakeAPI([issue("o/a", 1, "Done")])
    run_rollup(api, "o/a", 1)
    assert api.status_writes == []


def test_rollup_reads_cross_repo_child_status_from_the_parents_project():
    parent = issue("o/app", 1, "Ready")
    child = issue("o/lib", 2, parent=("o/app", 1), items=[Item("c1", LIB.id, "Done"), Item("c2", TT.id, "In review")])
    api = FakeAPI([parent, child], children={("o/app", 1): [("o/lib", 2)]})
    run_rollup(api, "o/lib", 2)
    assert api.status_writes == [("I_P_TT_1", "In review")]


def test_rollup_reopened_child_pulls_parent_out_of_done():
    parent = issue("o/a", 1, "Done", closed=True)
    c1 = issue("o/a", 2, "Done", parent=("o/a", 1))
    c2 = issue("o/a", 3, "Backlog", parent=("o/a", 1))
    api = FakeAPI([parent, c1, c2], children={("o/a", 1): [("o/a", 2), ("o/a", 3)]})
    run_rollup(api, "o/a", 3)
    assert api.status_writes == [("I_P_TT_1", "In progress")]


def test_rollup_walks_up_to_the_grandparent():
    gp = issue("o/a", 1, "Ready")
    p = issue("o/a", 2, "Ready", parent=("o/a", 1))
    c = issue("o/a", 3, "In progress", parent=("o/a", 2))
    api = FakeAPI([gp, p, c], children={("o/a", 1): [("o/a", 2)], ("o/a", 2): [("o/a", 3)]})
    run_rollup(api, "o/a", 3)
    assert api.status_writes == [("I_P_TT_2", "In progress"), ("I_P_TT_1", "In progress")]


def test_rollup_does_not_rewrite_an_unchanged_status():
    parent = issue("o/a", 1, "In progress")
    c = issue("o/a", 2, "In progress", parent=("o/a", 1))
    api = FakeAPI([parent, c], children={("o/a", 1): [("o/a", 2)]})
    run_rollup(api, "o/a", 2)
    assert api.status_writes == []


def test_ci_bug_files_a_bug_that_references_the_merge():
    api = FakeAPI([])
    run_ci_bug(api, "o/a", "abc1234", "https://example/run/1", 12)
    repo, title, body = api.bugs[0]
    assert repo == "o/a" and "abc1234" in title
    assert "#12" in body and "https://example/run/1" in body


def test_sweep_rolls_up_every_open_issue_that_has_a_parent():
    from cli import run_sweep
    parent = issue("o/a", 1, "Ready")
    c = issue("o/a", 2, "In progress", parent=("o/a", 1))
    api = FakeAPI([parent, c], children={("o/a", 1): [("o/a", 2)]})
    api.open_with_parent = {"o/a": [2]}
    run_sweep(api, "o/a")
    assert api.status_writes == [("I_P_TT_1", "In progress")]
