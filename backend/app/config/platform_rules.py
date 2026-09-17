"""Load platform detection rules from YAML config."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_RULES_PATH = Path(__file__).resolve().parent / "platform_rules.yaml"


@lru_cache(maxsize=1)
def _load_rules() -> dict[str, Any]:
    with _RULES_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _fragment_rules(section: str) -> list[tuple[str, str]]:
    rows = _load_rules().get(section) or []
    return [(row["fragment"], row["platform"]) for row in rows if row.get("fragment")]


def get_assessor_platform_rules() -> list[tuple[str, str]]:
    return _fragment_rules("assessor")


def get_recorder_platform_rules() -> list[tuple[str, str]]:
    return _fragment_rules("recorder")


def get_tax_platform_rules() -> list[tuple[str, str]]:
    return _fragment_rules("tax")


def get_assessor_search_overrides() -> dict[str, str]:
    return dict(_load_rules().get("assessor_search_overrides") or {})


def get_recorder_search_overrides() -> dict[str, str]:
    return dict(_load_rules().get("recorder_search_overrides") or {})


def get_tax_host_overrides() -> dict[str, str]:
    return dict(_load_rules().get("tax_host_overrides") or {})


def get_tax_assessor_platforms() -> frozenset[str]:
    return frozenset(_load_rules().get("tax_assessor_platforms") or [])
