from __future__ import annotations

from pathlib import Path

import yaml

from tl_towerwatch.config import Settings


def load_config_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text().strip()
    if not text:
        return {}
    return yaml.safe_load(text) or {}


def save_config_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(yaml.safe_dump(data, sort_keys=False))
    tmp.replace(path)


def merge_into_settings(settings: Settings, data: dict) -> None:
    """Top-level keys in `data` override the matching `settings` field."""
    for k, v in data.items():
        if not hasattr(settings, k):
            continue
        current = getattr(settings, k)
        if isinstance(v, dict) and hasattr(current, "__pydantic_fields__"):
            for sk, sv in v.items():
                if sk in current.__pydantic_fields__:
                    setattr(current, sk, sv)
        else:
            setattr(settings, k, v)