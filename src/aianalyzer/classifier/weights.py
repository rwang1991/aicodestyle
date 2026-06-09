"""YAML-backed classifier weights loader."""
from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Optional

import yaml


@dataclass(frozen=True)
class _Range:
    min: float
    max: float


@dataclass(frozen=True)
class Weights:
    planning: dict[str, float]
    control: dict[str, float]
    normalizers: dict[str, _Range]
    modifiers: dict[str, float]

    def normalize(self, signal: str, value: float) -> float:
        rng = self.normalizers.get(signal)
        if rng is None:
            return value
        if rng.max == rng.min:
            return 0.0
        scaled = (value - rng.min) / (rng.max - rng.min)
        return max(0.0, min(1.0, scaled))


def load_weights(path: Optional[Path] = None) -> Weights:
    if path is None:
        data = yaml.safe_load(
            resources.files("aianalyzer.classifier").joinpath("weights.yaml").read_text(encoding="utf-8")
        )
    else:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))

    normalizers = {k: _Range(min=v["min"], max=v["max"]) for k, v in data["normalizers"].items()}
    return Weights(
        planning=dict(data["planning"]),
        control=dict(data["control"]),
        normalizers=normalizers,
        modifiers=dict(data["modifiers"]),
    )
