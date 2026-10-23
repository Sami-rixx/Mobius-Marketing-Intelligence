"""Load the brand materials the lints enforce.

Everything here is founder-authored Markdown/JSON. Nothing is generated.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .config import RepoPaths
from .errors import ConfigError

FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)
YAML_BLOCK_RE = re.compile(r"```yaml\s*\n(.*?)```", re.DOTALL)


@dataclass(frozen=True)
class VoiceSample:
    path: Path
    context: str
    source: str
    text: str


@dataclass
class BrandMaterials:
    rules: dict[str, Any]
    fingerprint_raw: str
    fingerprint: dict[str, Any]
    samples: list[VoiceSample] = field(default_factory=list)

    @property
    def calibrated(self) -> bool:
        return bool(self.fingerprint.get("calibrated")) and len(self.samples) >= int(
            (self.fingerprint.get("similarity") or {}).get("min_library_samples", 3)
        )

    @property
    def palette(self) -> list[str]:
        return [value.upper() for value in self.rules.get("palette_hex", [])]


def _read(path: Path) -> str:
    if not path.exists():
        raise ConfigError(f"brand file missing: {path}")
    return path.read_text(encoding="utf-8")


def load_fingerprint(path: Path) -> tuple[str, dict[str, Any]]:
    raw = _read(path)
    match = YAML_BLOCK_RE.search(raw)
    if not match:
        raise ConfigError(f"voice fingerprint has no ```yaml block: {path}")
    try:
        data = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"voice fingerprint YAML block is invalid: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"voice fingerprint YAML block must be a mapping: {path}")
    if not data.get("version"):
        raise ConfigError(f"voice fingerprint YAML block must declare a version: {path}")
    return raw, data


def load_voice_library(directory: Path) -> list[VoiceSample]:
    samples: list[VoiceSample] = []
    if not directory.exists():
        return samples
    for path in sorted(directory.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        raw = path.read_text(encoding="utf-8")
        match = FRONT_MATTER_RE.match(raw)
        if not match:
            raise ConfigError(f"voice sample missing front matter: {path}")
        try:
            meta = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"voice sample front matter invalid: {path}: {exc}") from exc
        if meta.get("synthetic") is not False:
            raise ConfigError(
                f"voice sample {path.name} is not marked synthetic: false — "
                "synthetic brand voice is forbidden (docs/05-learning-loop.md)"
            )
        body = (match.group(2) or "").strip()
        if len(body.split()) < 10:
            raise ConfigError(f"voice sample too short to be useful: {path}")
        samples.append(
            VoiceSample(
                path=path,
                context=str(meta.get("context") or "unknown"),
                source=str(meta.get("source") or "unspecified"),
                text=body,
            )
        )
    return samples


def load_brand(paths: RepoPaths) -> BrandMaterials:
    rules_path = paths.brand / "lint-rules.json"
    try:
        rules = json.loads(_read(rules_path))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"brand/lint-rules.json is not valid JSON: {exc}") from exc
    fingerprint_raw, fingerprint = load_fingerprint(paths.brand / "voice-fingerprint.md")
    samples = load_voice_library(paths.brand / "voice-library")
    return BrandMaterials(
        rules=rules,
        fingerprint_raw=fingerprint_raw,
        fingerprint=fingerprint,
        samples=samples,
    )


def render_fingerprint_for_prompt(materials: BrandMaterials) -> str:
    """The fingerprint as the Producer sees it: prose + machine block + real samples."""
    parts = [materials.fingerprint_raw.strip()]
    if materials.samples:
        parts.append("\n## Voice library samples (verbatim, real)\n")
        for sample in materials.samples:
            parts.append(f"### {sample.context} — {sample.source}\n{sample.text}")
    else:
        parts.append(
            "\n## Voice library samples\n\nNone yet. Do not imitate an invented voice: "
            "write plainly, specifically, and without hype."
        )
    return "\n".join(parts)
