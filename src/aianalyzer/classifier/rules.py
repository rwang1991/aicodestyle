"""Archetype classification from a UserProfile."""
from __future__ import annotations

from aianalyzer.classifier.archetypes import Archetype, ClassificationResult
from aianalyzer.classifier.weights import Weights, load_weights
from aianalyzer.features import UserProfile


def _signal_value(profile: UserProfile, name: str) -> float:
    if name == "todo_density":
        sessions = max(profile.session_count, 1)
        return profile.total_todos / sessions
    return float(getattr(profile, name, 0.0))


def _axis_score(profile: UserProfile, weights: dict[str, float], w: Weights) -> float:
    total = 0.0
    denom = 0.0
    for signal, coeff in weights.items():
        raw = _signal_value(profile, signal)
        norm = w.normalize(signal, raw)
        # Center normalized value around 0: 0.0 -> -1.0, 0.5 -> 0.0, 1.0 -> +1.0.
        # That way a coefficient's *sign* always controls direction, and high
        # normalized values push the axis along that direction.
        signed = 2.0 * norm - 1.0
        total += coeff * signed
        denom += abs(coeff)
    if denom == 0.0:
        return 0.0
    return max(-1.0, min(1.0, total / denom))


_QUADRANT: dict[tuple[bool, bool], Archetype] = {
    (True, True): Archetype.ARCHITECT,
    (True, False): Archetype.PILOT,
    (False, True): Archetype.TINKERER,
    (False, False): Archetype.VIBE_CODER,
}


def _primary(planning: float, control: float) -> Archetype:
    return _QUADRANT[(planning >= 0, control >= 0)]


def _secondary(planning: float, control: float, margin: float) -> Archetype | None:
    plan_close = abs(planning) < margin
    ctrl_close = abs(control) < margin
    if not plan_close and not ctrl_close:
        return None
    # Pick the axis closer to zero to flip; tie -> flip planning.
    if plan_close and (not ctrl_close or abs(planning) <= abs(control)):
        return _QUADRANT[(not (planning >= 0), control >= 0)]
    return _QUADRANT[(planning >= 0, not (control >= 0))]


def _modifiers(profile: UserProfile, w: Weights) -> list[str]:
    m = w.modifiers
    tags: list[str] = []
    if profile.question_ratio >= m["questioner_min_question_ratio"]:
        tags.append("questioner")
    if profile.tool_error_rate >= m["debugger_min_tool_error_rate"]:
        tags.append("debugger")
    todo_density = profile.total_todos / max(profile.session_count, 1)
    if todo_density >= m["planner_min_todo_density"]:
        tags.append("planner")
    if profile.accept_and_go_ratio >= m["yolo_min_accept_and_go"]:
        tags.append("yolo")
    if profile.parallel_tool_call_rate >= m["parallelist_min_parallel_tool_call_rate"]:
        tags.append("parallelist")
    return tags


def classify(profile: UserProfile, weights: Weights | None = None) -> ClassificationResult:
    w = weights or load_weights()
    planning = _axis_score(profile, w.planning, w)
    control = _axis_score(profile, w.control, w)
    primary = _primary(planning, control)
    secondary = _secondary(planning, control, margin=0.15)
    tags = _modifiers(profile, w)

    primary_label = primary.value.replace("-", " ").title()
    label = primary_label
    if secondary is not None:
        label += f" / {secondary.value.replace('-', ' ').title()}"
    if tags:
        label += f" ({', '.join(tags)})"

    return ClassificationResult(
        planning_score=planning,
        control_score=control,
        primary=primary,
        secondary=secondary,
        tags=tags,
        macro_label=label,
        secondary_margin=0.15,
    )
