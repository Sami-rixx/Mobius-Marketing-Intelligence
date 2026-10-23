"""Shared test fixtures.

Tests never write into the repository's real content, claims or analytics directories: they
use tmp_path for outputs and read-only fixtures for the registry and brand materials.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from amplify.brand import load_brand  # noqa: E402
from amplify.config import load_config, repo_paths  # noqa: E402
from amplify.registry import Registry  # noqa: E402


@pytest.fixture(scope="session")
def paths():
    return repo_paths(ROOT)


@pytest.fixture(scope="session")
def config(paths):
    return load_config(root=paths.root)


@pytest.fixture()
def materials(paths):
    """Function-scoped: tests mutate voice calibration, so state must not leak."""
    return load_brand(paths)


@pytest.fixture()
def demo_registry(paths) -> Registry:
    return Registry.load(paths, path=paths.fixtures / "demo" / "registry.json")


@pytest.fixture()
def empty_registry() -> Registry:
    return Registry(entries={}, version=1, updated=None, source=None)


def temp_repo(tmp_path: Path, paths) -> "object":
    """Build an isolated repository root: real read-only assets, throwaway state dirs.

    ``docs/``, ``brand/``, ``agents/``, ``schemas/`` and ``tests/`` are symlinked from the
    checkout; content, strategy state, claims and analytics are fresh so tests cannot touch
    the founder's real work.
    """
    import os

    from amplify.config import repo_paths

    root = tmp_path / "repo"
    root.mkdir(parents=True, exist_ok=True)
    for name in ("docs", "brand", "agents", "schemas", "tests"):
        link = root / name
        if not link.exists():
            os.symlink(paths.root / name, link)
    for relative in (
        "content/drafts",
        "content/review",
        "content/calendar",
        "strategy/research",
        "strategy/plans",
        "analytics/raw",
        "claims",
        "amplify",
    ):
        (root / relative).mkdir(parents=True, exist_ok=True)
    import shutil

    shutil.copy(paths.config_file, root / "amplify" / "config.yaml")
    for name in ("scores.json", "formats.yaml", "audiences.yaml", "positioning.md"):
        shutil.copy(paths.strategy / name, root / "strategy" / name)
    shutil.copy(paths.claims, root / "claims" / "registry.json")
    return repo_paths(root)


def draft_item(**overrides):
    """A schema-valid draft based on the dry-run hero fixture."""
    raw = json.loads((ROOT / "tests" / "fixtures" / "dryrun" / "2026-W43-producer-hero.json").read_text())
    item = copy.deepcopy(raw)
    item["week"] = "2026-W43"
    item.update(overrides)
    return item


def review_item(composite: float = 88.0, **overrides):
    """A schema-valid in_review item with QA scores."""
    item = draft_item(**overrides)
    item["scores"] = {
        "hook_strength": 90.0,
        "specificity_evidence": 90.0,
        "clarity": 90.0,
        "brand_fit": 90.0,
        "platform_fit": 90.0,
        "composite": composite,
    }
    item["status"] = "in_review"
    return item
