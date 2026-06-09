"""Verify the project is installable and exposes the expected console script."""
from importlib import metadata


def test_distribution_metadata():
    dist = metadata.distribution("aianalyzer")
    assert dist.version == "0.1.0"
    entry_points = {ep.name: ep.value for ep in dist.entry_points}
    assert entry_points.get("aianalyzer") == "aianalyzer.cli:app"
