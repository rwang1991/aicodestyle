from aianalyzer.classifier.archetypes import Archetype
from aianalyzer.classifier.rules import classify
from aianalyzer.classifier.weights import load_weights
from aianalyzer.features import UserProfile


def _profile(**overrides):
    base = dict(session_count=1, total_turns=10, total_todos=0)
    base.update(overrides)
    return UserProfile(**base)


def test_questioner_tag_applied():
    r = classify(_profile(question_ratio=0.5), weights=load_weights())
    assert "questioner" in r.tags


def test_yolo_tag_applied_when_accept_and_go_high():
    r = classify(_profile(accept_and_go_ratio=0.6), weights=load_weights())
    assert "yolo" in r.tags


def test_parallelist_and_debugger_tags():
    r = classify(
        _profile(parallel_tool_call_rate=0.5, tool_error_rate=0.3),
        weights=load_weights(),
    )
    assert "parallelist" in r.tags
    assert "debugger" in r.tags


def test_planner_tag_when_todo_density_high():
    r = classify(_profile(session_count=2, total_todos=4), weights=load_weights())
    # density = 4 / 2 = 2.0 >= 1.0
    assert "planner" in r.tags


def test_macro_label_includes_tags_and_secondary():
    weights = load_weights()
    p = _profile(
        planning_language_ratio=0.3,
        question_ratio=0.5,  # questioner
        tool_diversity=2.0,
        edited_files_per_turn_avg=4.0,
    )
    r = classify(p, weights=weights)
    assert r.primary.value.replace("-", " ").title() in r.macro_label
    assert "questioner" in r.macro_label
    if r.secondary is not None:
        assert r.secondary.value.replace("-", " ").title() in r.macro_label
