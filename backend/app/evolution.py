"""Compatibility exports for the PRD-standard LangGraph evolution workflow."""

from dataclasses import dataclass

from .standard_evolution import (
    EvolutionAgentError,
    LangGraphEvolutionPipeline,
    _parse_json,
    _quality,
    run_evolution_agents,
)


@dataclass(frozen=True)
class QualityResult:
    passed: bool
    score: int
    issues: list[str]
    similarity: float


def _parse_json_object(value: str) -> dict:
    return _parse_json(value)


def evaluate_evolution_quality(original: str, evolved: str, key_points: list[str]) -> QualityResult:
    passed, issues, similarity = _quality(original, evolved, key_points)
    return QualityResult(
        passed=passed,
        score=max(0, 100 - len(issues) * 18),
        issues=issues,
        similarity=similarity,
    )


EvolutionAgentPipeline = LangGraphEvolutionPipeline

__all__ = [
    "EvolutionAgentError",
    "EvolutionAgentPipeline",
    "QualityResult",
    "_parse_json_object",
    "evaluate_evolution_quality",
    "run_evolution_agents",
]
