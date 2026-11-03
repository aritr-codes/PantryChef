"""Results-file helper (M2). Every published number links to one of these files.

The contract is ``results/schema.v1.json``. ``web/scripts/result.mjs`` writes the same shape.
No third-party validator is used: ``validate`` checks the required keys and types by hand.

``METRICS`` and ``ARMS`` are fixed registries. A caller cannot declare its own role or
dependencies. A metric or arm that is not listed cannot be written (ADR 0005). A metric that
selects a model must not be a function of the features of that model.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
LABELS = ("MEASURED", "ESTIMATE", "HYPOTHESIS")
ROLES = ("selection", "sanity", "product", "latency")


@dataclass(frozen=True)
class MetricSpec:
    role: str
    depends_on: tuple[str, ...]
    justification: str = ""  # required for role "selection"


# Registry entries are filled in by Lane A (task A3) from plan section 3.
METRICS: dict[str, MetricSpec] = {}
# Arm name -> features the order of that arm uses.
ARMS: dict[str, tuple[str, ...]] = {}


class NotSelectable(ValueError):
    """Raised when a metric may not choose between arms."""


def git_facts(root: Path, exclude: tuple[Path, ...] = ()) -> tuple[str, bool, list[str]]:
    """Return ``(commit, dirty, dirty_paths)``. Paths in ``exclude`` do not count as dirty."""
    raise NotImplementedError


def validate(doc: dict[str, Any]) -> None:
    """Raise ``ValueError`` when ``doc`` breaks the schema. Check metrics against ``METRICS``."""
    raise NotImplementedError


def assert_selectable(metric: str, arms: list[str]) -> None:
    """Raise ``NotSelectable`` unless ``metric`` has role ``selection``.

    Also raise when a dependency of the metric is a feature of any arm.
    """
    raise NotImplementedError


def write_result(path: Path, doc: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    """Fill commit, dirty, dirty_paths, environment, schema; validate; write sorted JSON."""
    raise NotImplementedError


def load_result(path: Path) -> dict[str, Any]:
    """Read a results file and validate it."""
    raise NotImplementedError
