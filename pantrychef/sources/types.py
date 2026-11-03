"""Source-neutral recipe record with provenance."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceRecipe:
    recipe_id: str
    title: str
    page: str  # wiki page title, for example "Cookbook:Apple Cobbler"
    url: str
    revision_id: int
    revision_url: str
    licence: str
    retrieved_on: str
    ingredient_lines: tuple[str, ...]
    steps: tuple[str, ...]
    category: str | None = None
    servings: str | None = None
    time: str | None = None
