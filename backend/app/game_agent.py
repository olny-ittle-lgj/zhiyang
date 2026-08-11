"""Compatibility exports for the PRD-standard game Agent implementation."""

from .standard_game_agent import (
    GAME_TITLES,
    agent_extract_knowledge,
    build_game_questions,
    index_matching_points,
    matching_round,
)

__all__ = [
    "GAME_TITLES",
    "agent_extract_knowledge",
    "build_game_questions",
    "index_matching_points",
    "matching_round",
]
