"""Tests for session type classifier (Task 24)."""
from aianalyzer.classifier.session_types import SessionType, classify_session_type


def _call(**overrides):
    """Helper to call classify_session_type with defaults + overrides."""
    base = dict(
        turns=10,
        duration_seconds=900.0,
        tool_error_rate=0.0,
        debug_kw_density=0.0,
        test_or_spec_mention_rate=0.0,
        majority_test_files=False,
        majority_doc_files=False,
        planning_language=0.0,
        todos_count=0,
        edited_files_per_turn=0.4,  # below FEATURE_WORK threshold (0.5)
        question_ratio=0.0,
        refactor_kw_density=0.0,
        review_kw_density=0.0,
        edit_tool_calls=2,
        create_tool_calls=0,
    )
    base.update(overrides)
    return classify_session_type(**base)


def test_quick_task_rule_fires_first():
    """Quick tasks are <= 3 turns and < 300 seconds."""
    result = _call(turns=2, duration_seconds=120.0)
    assert result == SessionType.QUICK_TASK


def test_debugging_rule_on_tool_error_rate():
    """High tool error rate triggers debugging."""
    result = _call(tool_error_rate=0.5)
    assert result == SessionType.DEBUGGING


def test_debugging_rule_on_debug_keywords():
    """High debug keyword density triggers debugging."""
    result = _call(debug_kw_density=0.2)
    assert result == SessionType.DEBUGGING


def test_testing_rule_on_test_mentions():
    """High test/spec mention rate triggers testing."""
    result = _call(test_or_spec_mention_rate=0.5)
    assert result == SessionType.TESTING


def test_testing_rule_on_majority_test_files():
    """Majority test files triggers testing."""
    result = _call(majority_test_files=True)
    assert result == SessionType.TESTING


def test_documentation_rule():
    """Majority doc files triggers documentation."""
    result = _call(majority_doc_files=True)
    assert result == SessionType.DOCUMENTATION


def test_planning_rule_requires_all_three():
    """Planning needs planning language + todos + low edit rate."""
    result = _call(
        planning_language=0.4,
        todos_count=3,
        edited_files_per_turn=0.2,
    )
    assert result == SessionType.PLANNING


def test_exploration_rule():
    """High question ratio + low edit rate triggers exploration."""
    result = _call(question_ratio=0.5, edited_files_per_turn=0.1)
    assert result == SessionType.EXPLORATION


def test_refactoring_rule_needs_edits_no_creates():
    """Refactoring needs refactor keywords + edits but no creates."""
    result = _call(
        refactor_kw_density=0.15,
        edit_tool_calls=5,
        create_tool_calls=0,
    )
    assert result == SessionType.REFACTORING


def test_code_review_rule_needs_zero_edits_and_creates():
    """Code review needs review keywords but no edits or creates."""
    result = _call(
        review_kw_density=0.2,
        edit_tool_calls=0,
        create_tool_calls=0,
    )
    assert result == SessionType.CODE_REVIEW


def test_feature_work_rule():
    """High edit rate triggers feature work."""
    result = _call(edited_files_per_turn=0.8, create_tool_calls=2)
    assert result == SessionType.FEATURE_WORK


def test_mixed_is_the_fallback():
    """With all defaults, session is classified as mixed."""
    result = _call()
    assert result == SessionType.MIXED
