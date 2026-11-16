import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from logic import parse_tracking, projects_to_add, rollup_status  # noqa: E402

TT = "binary-companion/timetug"
LIB = "binary-companion/libraries"


def test_parse_tracking_reads_projects():
    assert parse_tracking(f"projects: [{LIB}]") == [LIB]


def test_parse_tracking_several_projects():
    assert parse_tracking(f"projects: [{TT}, {LIB}]") == [TT, LIB]


def test_parse_tracking_empty_missing_key_or_malformed_means_untracked():
    assert parse_tracking("") == []
    assert parse_tracking("other: 1") == []
    assert parse_tracking("::: not yaml [") == []
    assert parse_tracking("projects: not-a-list") == []
    assert parse_tracking("projects: [1, null]") == []


def test_projects_to_add_adds_those_not_joined():
    assert projects_to_add([TT, LIB], {TT}) == [LIB]


def test_projects_to_add_nothing_when_already_in_all():
    assert projects_to_add([TT], {TT, LIB}) == []


def test_projects_to_add_empty_list_means_untracked():
    assert projects_to_add([], set()) == []


def test_rollup_no_children_is_no_change():
    assert rollup_status([]) is None


def test_rollup_any_in_progress_is_in_progress():
    assert rollup_status(["In progress", "Backlog"]) == "In progress"


def test_rollup_done_and_in_review_is_in_review():
    assert rollup_status(["In review", "Done"]) == "In review"


def test_rollup_in_review_with_unstarted_child_is_no_change():
    assert rollup_status(["In review", "Backlog"]) is None


def test_rollup_all_done_is_done():
    assert rollup_status(["Done", "Done"]) == "Done"


def test_rollup_done_with_in_progress_is_in_progress():
    assert rollup_status(["Done", "In progress"]) == "In progress"


def test_rollup_reopened_child_leaves_done():
    assert rollup_status(["Done", "Backlog"]) is None


def test_rollup_untracked_child_counts_by_issue_state():
    assert rollup_status([None, "Done"], closed=[True, False]) == "Done"
    assert rollup_status([None, "Done"], closed=[False, False]) is None


def test_rollup_archived_child_still_counts_as_done():
    assert rollup_status(["Done", "Done"]) == "Done"
