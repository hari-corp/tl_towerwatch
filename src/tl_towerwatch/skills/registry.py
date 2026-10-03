from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import yaml

@dataclass
class Skill:
    name: str
    description: str
    cli_flag: str
    enabled: bool = True

def default_registry() -> list[Skill]:
    return [
        Skill("superpowers",
              "Set of code-review and quality skills (requesting-code-review, verification-before-completion)",
              "--enable-superpowers", True),
        Skill("ponytail",
              "Custom review heuristics",
              "--skill ponytail", True),
    ]

def load_registry(data_dir: Path) -> list[Skill]:
    cfg = data_dir / "config.yaml"
    if not cfg.exists():
        return default_registry()
    data = yaml.safe_load(cfg.read_text()) or {}
    raw = data.get("skills", {})
    out: list[Skill] = []
    for name, val in raw.items():
        if isinstance(val, dict):
            out.append(Skill(
                name=name,
                description=val.get("description", ""),
                cli_flag=val.get("cli_flag", f"--skill {name}"),
                enabled=bool(val.get("enabled", True)),
            ))
    return out or default_registry()