from aianalyzer.classifier.weights import Weights, load_weights


def test_load_default_weights():
    w = load_weights()
    assert isinstance(w, Weights)
    assert w.planning["planning_language_ratio"] == 1.0
    assert w.control["accept_and_go_ratio"] == -1.0
    assert w.normalizers["planning_language_ratio"].max == 0.6
    assert w.modifiers["questioner_min_question_ratio"] == 0.4


def test_normalize_clamps_to_unit_interval():
    w = load_weights()
    norm = w.normalize("planning_language_ratio", 0.3)
    # (0.3 - 0.0) / (0.6 - 0.0) = 0.5
    assert abs(norm - 0.5) < 1e-9
    assert w.normalize("planning_language_ratio", -1.0) == 0.0
    assert w.normalize("planning_language_ratio", 99.0) == 1.0
    assert w.normalize("unknown_signal", 5.0) == 5.0  # unmapped -> passthrough
