from datetime import datetime, timezone

from aianalyzer.classifier.archetypes import Archetype
from aianalyzer.classifier.rules import classify
from aianalyzer.classifier.weights import load_weights
from aianalyzer.features import UserProfile


def _profile(**overrides) -> UserProfile:
    base = dict(session_count=1, total_turns=10, total_todos=0)
    base.update(overrides)
    return UserProfile(**base)


def test_architect_quadrant_high_planning_high_control():
    weights = load_weights()
    p = _profile(
        planning_language_ratio=0.6,
        question_ratio=0.5,
        thinks_before_prompt_sec_avg=60.0,
        test_or_spec_mention_rate=0.4,
        total_todos=3,
        tool_diversity=2.0,
        edited_files_per_turn_avg=3.0,
        accept_and_go_ratio=0.0,
        revision_depth=0.5,
        tool_error_rate=0.1,
    )
    r = classify(p, weights=weights)
    assert r.primary == Archetype.ARCHITECT
    assert r.planning_score > 0
    assert r.control_score > 0


def test_vibe_coder_quadrant_low_planning_low_control():
    weights = load_weights()
    p = _profile(
        planning_language_ratio=0.0,
        question_ratio=0.0,
        thinks_before_prompt_sec_avg=2.0,
        test_or_spec_mention_rate=0.0,
        total_todos=0,
        tool_diversity=0.2,
        edited_files_per_turn_avg=0.5,
        accept_and_go_ratio=0.6,
        revision_depth=3.0,
        tool_error_rate=0.0,
    )
    r = classify(p, weights=weights)
    assert r.primary == Archetype.VIBE_CODER
    assert r.planning_score < 0
    assert r.control_score < 0


def test_pilot_quadrant_high_planning_low_control():
    weights = load_weights()
    p = _profile(
        # All planning signals high (matches the Architect test on the planning side)
        planning_language_ratio=0.6,
        question_ratio=0.5,
        thinks_before_prompt_sec_avg=60.0,
        test_or_spec_mention_rate=0.4,
        total_todos=3,
        # Hands-off control side
        accept_and_go_ratio=0.5,
        revision_depth=3.0,
        tool_diversity=0.0,
        edited_files_per_turn_avg=0.0,
    )
    r = classify(p, weights=weights)
    assert r.primary == Archetype.PILOT
    assert r.planning_score > 0
    assert r.control_score < 0


def test_tinkerer_quadrant_low_planning_high_control():
    weights = load_weights()
    p = _profile(
        planning_language_ratio=0.0,
        question_ratio=0.0,
        thinks_before_prompt_sec_avg=0.0,
        tool_diversity=2.0,
        edited_files_per_turn_avg=5.0,
        accept_and_go_ratio=0.0,
        revision_depth=0.5,
    )
    r = classify(p, weights=weights)
    assert r.primary == Archetype.TINKERER


def test_secondary_set_when_planning_axis_near_zero():
    weights = load_weights()
    # Every planning signal at its normalizer midpoint -> planning_score == 0.
    # Control signals strongly hands-on -> control_score > margin.
    p = _profile(
        planning_language_ratio=0.3,   # 0.6/2
        question_ratio=0.3,            # 0.6/2
        thinks_before_prompt_sec_avg=30.0,  # 60/2
        test_or_spec_mention_rate=0.2,  # 0.4/2
        total_todos=1,                  # todo_density=1.0 -> 2.0/2
        tool_diversity=2.0,
        edited_files_per_turn_avg=4.0,
        accept_and_go_ratio=0.0,
    )
    r = classify(p, weights=weights)
    # With planning ~ 0, primary lands in the control-positive row
    # (Architect when planning >= 0, Tinkerer when planning < 0) and the
    # secondary flips the close axis.
    assert r.secondary in {Archetype.ARCHITECT, Archetype.TINKERER}
    assert r.primary != r.secondary
