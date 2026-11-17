import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cli import run_add, run_ci_bug, run_rollup  # noqa: E402
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
        self.closed_issues = []
        self.reopened_issues = []
        self.fields = []
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
        self.issues[(repo, 99)] = Issue("N99", repo, 99)
        return 99

    def close_issue(self, issue):
        self.closed_issues.append(issue.number)
        issue.closed = True

    def reopen_issue(self, issue):
        self.reopened_issues.append(issue.number)
        issue.closed = False

    def set_issue_field(self, repo, number, field, value):
        self.fields.append((repo, number, field, value))


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


def test_rollup_reads_a_child_that_is_only_in_its_own_projects():
    parent = issue("o/app", 1, "Ready")
    child = issue("o/lib", 2, parent=("o/app", 1), items=[Item("c1", LIB.id, "Done")])
    api = FakeAPI([parent, child], children={("o/app", 1): [("o/lib", 2)]})
    run_rollup(api, "o/lib", 2)
    assert api.status_writes == [("I_P_TT_1", "Done")]


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


def test_pr_check_passes_when_the_pr_closes_an_issue():
    from cli import run_pr_check
    api = FakeAPI([], closing={("o/a", 7): [("o/a", 1)]})
    assert run_pr_check(api, "o/a", 7, "Fixes #1", "someone") == (True, "")


def test_pr_check_passes_when_the_pr_mentions_no_issue():
    """A pull request that is not part of a story needs no issue."""
    from cli import run_pr_check
    api = FakeAPI([])
    assert run_pr_check(api, "o/a", 7, "Fix a typo", "someone") == (True, "")


def test_pr_check_fails_when_it_mentions_an_issue_without_a_closing_link():
    from cli import run_pr_check
    api = FakeAPI([])
    for body in ("Part of #203", "Part of binary-companion/timetug#203", "Related to #5"):
        ok, message = run_pr_check(api, "o/a", 7, body, "someone")
        assert ok is False and "Fixes #" in message and "sub-issue" in message


def test_pr_check_ignores_a_pr_number_inside_a_word_or_url_fragment():
    from cli import run_pr_check
    api = FakeAPI([])
    assert run_pr_check(api, "o/a", 7, "see abc#12def and http://x/y#3", "someone")[0] is True


def test_pr_check_exempts_bots():
    from cli import run_pr_check
    api = FakeAPI([])
    assert run_pr_check(api, "o/a", 7, "Part of #5", "dependabot[bot]")[0] is True
    assert run_pr_check(api, "o/a", 7, "Part of #5", "timetug-bot")[0] is True


class SweepAPI(FakeAPI):
    """A fake with the extra discovery calls the whole-organization sweep needs."""

    def __init__(self, repos, scans=None, open_prs=None, merged_prs=None, failures=None, bugs=(), **kw):
        super().__init__(**kw)
        self.repos = repos
        self.scans = scans or {}
        self._open_prs = open_prs or {}
        self._merged_prs = merged_prs or {}
        self.failures = failures or {}
        self.bugs_seen = set(bugs)

    def tracked_repos(self):
        return self.repos

    def scan(self, repo):
        return self.scans.get(repo, [])

    def open_prs(self, repo):
        return self._open_prs.get(repo, [])

    def merged_prs(self, repo):
        return self._merged_prs.get(repo, [])

    def latest_failure(self, repo):
        return self.failures.get(repo)

    def bug_exists(self, repo, sha):
        return (repo, sha[:7]) in self.bugs_seen


def test_sweep_all_skips_repos_without_a_tracking_list():
    from cli import run_sweep_all
    api = SweepAPI({"o/web": "", "o/a": "projects: [binary-companion/timetug]"},
                   scans={"o/web": [(1, False, False, False)], "o/a": [(2, False, False, False)]},
                   issues=[issue("o/web", 1), issue("o/a", 2)])
    run_sweep_all(api)
    assert api.added == [("P_TT", 2)]


def test_sweep_all_rolls_up_parents_of_scanned_issues():
    from cli import run_sweep_all
    parent = issue("o/a", 1, "Ready")
    child = issue("o/a", 2, "In progress", parent=("o/a", 1))
    api = SweepAPI({"o/a": "projects: [binary-companion/timetug]"},
                   scans={"o/a": [(2, False, True, False)]}, children={("o/a", 1): [("o/a", 2)]},
                   issues=[parent, child])
    run_sweep_all(api)
    assert ("I_P_TT_1", "In progress") in api.status_writes


def test_sweep_all_files_one_bug_for_a_failed_default_branch_run():
    from cli import run_sweep_all
    api = SweepAPI({"o/a": "projects: [binary-companion/timetug]"},
                   failures={"o/a": ("abcdef1234567", "https://example/run/9", 12)}, issues=[])
    run_sweep_all(api)
    assert len(api.bugs) == 1 and "abcdef1" in api.bugs[0][1]


def test_sweep_all_does_not_file_a_second_bug_for_the_same_commit():
    from cli import run_sweep_all
    api = SweepAPI({"o/a": "projects: [binary-companion/timetug]"},
                   failures={"o/a": ("abcdef1234567", "https://example/run/9", None)},
                   bugs={("o/a", "abcdef1")}, issues=[])
    run_sweep_all(api)
    assert api.bugs == []


def test_sweep_all_keeps_going_when_one_repository_fails_and_reports_it():
    from cli import run_sweep_all

    class Flaky(SweepAPI):
        def scan(self, repo):
            if repo == "o/bad":
                raise RuntimeError("boom")
            return super().scan(repo)

    api = Flaky({"o/bad": "projects: [binary-companion/timetug]", "o/a": "projects: [binary-companion/timetug]"},
                scans={"o/a": [(2, False, False, False)]}, issues=[issue("o/a", 2)])
    failures = run_sweep_all(api)
    assert api.added == [("P_TT", 2)]
    assert [repo for repo, _ in failures] == ["o/bad"]


def test_rollup_pulls_an_in_review_parent_back_when_a_child_is_not_in_review():
    parent = issue("o/a", 1, "In review")
    c1 = issue("o/a", 2, "In review", parent=("o/a", 1))
    c2 = issue("o/a", 3, "Backlog", parent=("o/a", 1))
    api = FakeAPI([parent, c1, c2], children={("o/a", 1): [("o/a", 2), ("o/a", 3)]})
    run_rollup(api, "o/a", 3)
    assert api.status_writes == [("I_P_TT_1", "In progress")]


def test_rollup_closes_an_open_parent_when_every_child_is_closed():
    parent = issue("o/a", 1, "In progress")
    c1 = issue("o/a", 2, "Done", closed=True, parent=("o/a", 1))
    c2 = issue("o/a", 3, "Done", closed=True, parent=("o/a", 1))
    api = FakeAPI([parent, c1, c2], children={("o/a", 1): [("o/a", 2), ("o/a", 3)]})
    run_rollup(api, "o/a", 3)
    assert api.status_writes == [("I_P_TT_1", "Done")]
    assert api.closed_issues == [1]


def test_rollup_reopens_a_closed_parent_when_a_child_is_open():
    parent = issue("o/a", 1, "Done", closed=True)
    c1 = issue("o/a", 2, "Done", closed=True, parent=("o/a", 1))
    c2 = issue("o/a", 3, "Backlog", parent=("o/a", 1))
    api = FakeAPI([parent, c1, c2], children={("o/a", 1): [("o/a", 2), ("o/a", 3)]})
    run_rollup(api, "o/a", 3)
    assert api.reopened_issues == [1]


def test_rollup_leaves_a_parent_open_while_a_child_is_open():
    parent = issue("o/a", 1, "In progress")
    c1 = issue("o/a", 2, "Done", closed=True, parent=("o/a", 1))
    c2 = issue("o/a", 3, "In progress", parent=("o/a", 1))
    api = FakeAPI([parent, c1, c2], children={("o/a", 1): [("o/a", 2), ("o/a", 3)]})
    run_rollup(api, "o/a", 3)
    assert api.closed_issues == [] and api.reopened_issues == []


def test_add_marks_a_closed_issue_done_when_it_joins_a_project():
    api = FakeAPI([issue("o/a", 1, closed=True)])
    run_add(api, "o/a", 1, "projects: [binary-companion/timetug]", done=True)
    assert api.added == [("P_TT", 1)]
    assert api.status_writes == [("I_P_TT_1", "Done")]


def test_sweep_all_adds_a_recently_completed_closed_issue_as_done_but_not_other_closed_ones():
    from cli import run_sweep_all
    api = SweepAPI({"o/a": "projects: [binary-companion/timetug]"},
                   scans={"o/a": [(1, True, False, True), (2, True, False, False)]},
                   issues=[issue("o/a", 1, closed=True), issue("o/a", 2, closed=True)])
    run_sweep_all(api)
    assert api.added == [("P_TT", 1)]
    assert api.status_writes == [("I_P_TT_1", "Done")]


def test_ci_bug_is_ready_urgent_and_on_the_board():
    api = FakeAPI([])
    number = run_ci_bug(api, "o/a", "abc1234", "https://example/run/1", 12,
                        tracking_text="projects: [binary-companion/timetug]")
    assert number == 99
    assert api.added == [("P_TT", 99)]
    assert api.status_writes == [("I_P_TT_99", "Ready")]
    assert api.fields == [("o/a", 99, "Priority", "Urgent")]


def test_sweep_all_passes_the_repo_tracking_list_to_the_bug_filing():
    from cli import run_sweep_all
    api = SweepAPI({"o/a": "projects: [binary-companion/timetug]"},
                   failures={"o/a": ("abcdef1234567", "https://example/run/9", None)}, issues=[])
    run_sweep_all(api)
    assert api.status_writes == [("I_P_TT_99", "Ready")]
