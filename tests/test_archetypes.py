from aianalyzer.classifier.archetypes import Archetype, ClassificationResult


def test_archetype_values():
    assert Archetype.ARCHITECT.value == "architect"
    assert Archetype.PILOT.value == "pilot"
    assert Archetype.TINKERER.value == "tinkerer"
    assert Archetype.VIBE_CODER.value == "vibe-coder"


def test_classification_result_serializes():
    r = ClassificationResult(
        planning_score=0.4,
        control_score=-0.2,
        primary=Archetype.ARCHITECT,
        secondary=None,
        tags=["questioner"],
        macro_label="Architect (questioner)",
        secondary_margin=0.15,
    )

    payload = r.model_dump()
    assert payload["primary"] == "architect"
    assert payload["secondary"] is None
    assert payload["tags"] == ["questioner"]
    assert payload["macro_label"] == "Architect (questioner)"
