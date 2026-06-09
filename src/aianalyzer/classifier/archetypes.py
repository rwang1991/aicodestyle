"""Archetype enum and classifier result model."""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class Archetype(str, Enum):
    ARCHITECT = "architect"
    PILOT = "pilot"
    TINKERER = "tinkerer"
    VIBE_CODER = "vibe-coder"


class ClassificationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    planning_score: float = Field(..., ge=-1.0, le=1.0)
    control_score: float = Field(..., ge=-1.0, le=1.0)
    primary: Archetype
    secondary: Optional[Archetype] = None
    tags: list[str] = Field(default_factory=list)
    macro_label: str
    secondary_margin: float = 0.15
