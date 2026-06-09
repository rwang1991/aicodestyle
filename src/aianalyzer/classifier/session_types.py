"""Session type classifier (Task 24). 10 first-match-wins rules."""
from __future__ import annotations

from enum import Enum


class SessionType(str, Enum):
    """10 session purpose types."""
    QUICK_TASK    = "quick_task"
    DEBUGGING     = "debugging"
    TESTING       = "testing"
    DOCUMENTATION = "documentation"
    PLANNING      = "planning"
    EXPLORATION   = "exploration"
    REFACTORING   = "refactoring"
    CODE_REVIEW   = "code_review"
    FEATURE_WORK  = "feature_work"
    MIXED         = "mixed"


def classify_session_type(
    *,
    turns: int,
    duration_seconds: float,
    tool_error_rate: float,
    debug_kw_density: float,
    test_or_spec_mention_rate: float,
    majority_test_files: bool,
    majority_doc_files: bool,
    planning_language: float,
    todos_count: int,
    edited_files_per_turn: float,
    question_ratio: float,
    refactor_kw_density: float,
    review_kw_density: float,
    edit_tool_calls: int,
    create_tool_calls: int,
) -> SessionType:
    """
    Classify session purpose from primitive features (first-match-wins).
    
    All parameters are primitives to avoid circular import with features.py.
    """
    # Rule 1: Quick task
    if turns <= 3 and duration_seconds < 300.0:
        return SessionType.QUICK_TASK
    
    # Rule 2: Debugging
    if tool_error_rate >= 0.25 or debug_kw_density >= 0.15:
        return SessionType.DEBUGGING
    
    # Rule 3: Testing
    if test_or_spec_mention_rate >= 0.4 or majority_test_files:
        return SessionType.TESTING
    
    # Rule 4: Documentation
    if majority_doc_files:
        return SessionType.DOCUMENTATION
    
    # Rule 5: Planning
    if planning_language >= 0.3 and todos_count >= 2 and edited_files_per_turn < 0.5:
        return SessionType.PLANNING
    
    # Rule 6: Exploration
    if question_ratio >= 0.4 and edited_files_per_turn < 0.2:
        return SessionType.EXPLORATION
    
    # Rule 7: Refactoring
    if refactor_kw_density >= 0.1 and edit_tool_calls > 0 and create_tool_calls == 0:
        return SessionType.REFACTORING
    
    # Rule 8: Code review
    if review_kw_density >= 0.1 and edit_tool_calls == 0 and create_tool_calls == 0:
        return SessionType.CODE_REVIEW
    
    # Rule 9: Feature work
    if edited_files_per_turn >= 0.5:
        return SessionType.FEATURE_WORK
    
    # Rule 10: Mixed (fallback)
    return SessionType.MIXED
