from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import yaml


# Names of the three prompt slots every skill exposes. Kept as a
# module-level constant so the settings UI, the prompt assembly, and
# the load_registry helper all agree on the keys. Order matters: the
# review flow uses ``prompts[REVIEW]`` first, then ``post_review``,
# then ``check_resolved``.
PROMPT_SLOTS = ("review", "post_review", "check_resolved")


@dataclass
class Skill:
    """One entry in the skills registry.

    The ``prompts`` dict maps a slot name (``review`` / ``post_review`` /
    ``check_resolved``) to the prompt template body. Templates are
    plain text; the assembly layer fills ``{title}``, ``{body}``,
    ``{diff}``, ``{author}`` etc. at render time so the user only edits
    the static skeleton.
    """
    name: str
    description: str
    cli_flag: str
    enabled: bool = True
    prompts: dict[str, str] = field(default_factory=dict)


def _default_prompts() -> dict[str, str]:
    """Built-in prompt templates shipped with the app.

    The defaults are written so a fresh install produces useful prompts
    without forcing the user to type anything. Users edit them in
    /settings; edits persist to config.yaml.
    """
    return {
        "review": (
            "You are doing a focused code review of the diff below.\n"
            "Look for correctness, edge cases, security, performance, "
            "and readability issues. Output a numbered list of findings, "
            "each citing the file + line. Be specific and actionable.\n\n"
            "PR title: {title}\n"
            "Author: {author}\n"
            "PR description:\n{body}\n\n"
            "Diff:\n{diff}"
        ),
        "post_review": (
            "You are summarising the review findings below into a short "
            "report for the PR author. Categorise each finding (must-fix / "
            "nice-to-have / question), drop duplicates, and write a one-line "
            "summary at the top.\n\n"
            "PR title: {title}\n\n"
            "Findings:\n{findings}"
        ),
        "check_resolved": (
            "You are checking whether the author has addressed every review "
            "comment on the PR. For each previous finding below, mark it "
            "'resolved' (the PR addresses it) or 'pending' (still relevant). "
            "If the author added new code that supersedes the concern, mark "
            "it 'resolved' and cite the new commit.\n\n"
            "PR title: {title}\n\n"
            "Previous findings:\n{findings}\n\n"
            "Latest diff (so you can compare to the comments):\n{diff}"
        ),
    }


def default_registry() -> list[Skill]:
    return [
        Skill(name="superpowers",
              description="Code-review and quality skills (requesting-code-review, verification-before-completion).",
              cli_flag="--enable-superpowers",
              enabled=True,
              prompts=_default_prompts()),
        Skill(name="ponytail",
              description="Custom review heuristics.",
              cli_flag="--skill ponytail",
              enabled=True,
              prompts=_default_prompts()),
    ]


def _coerce_prompts(raw: Any) -> dict[str, str]:
    """Normalise the prompts block from config.yaml.

    The persisted shape is::

        prompts:
          review: |
            ...
          post_review: |
            ...
          check_resolved: |
            ...

    An entry can be missing for a slot — we fall back to the default
    so the user never gets an empty textbox.
    """
    if not isinstance(raw, dict):
        return _default_prompts()
    out = dict(_default_prompts())
    for slot, body in raw.items():
        if slot in PROMPT_SLOTS and isinstance(body, str) and body.strip():
            out[slot] = body
    return out


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
                prompts=_coerce_prompts(val.get("prompts")),
            ))
    return out or default_registry()


def save_registry(data_dir: Path, skills: list[Skill]) -> None:
    """Persist the skills registry to config.yaml.

    The rest of config.yaml is preserved (theme, auth, refresh interval)
    — we only replace the ``skills`` block so the user's other
    preferences don't get clobbered when they tweak prompts.
    """
    cfg_path = data_dir / "config.yaml"
    data: dict = {}
    if cfg_path.exists():
        try:
            data = yaml.safe_load(cfg_path.read_text()) or {}
        except Exception:
            data = {}
    skills_block: dict[str, dict] = {}
    for s in skills:
        skills_block[s.name] = {
            "enabled": bool(s.enabled),
            "cli_flag": s.cli_flag,
            "description": s.description,
            "prompts": dict(s.prompts),
        }
    data["skills"] = skills_block
    cfg_path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


def save_skills_to_yaml(data_dir: Path, skills: list[dict]) -> None:
    """Persist skills from the settings form. The form submits plain
    dicts (not Skill instances) so the layer that owns the I/O is
    decoupled from the dataclass. Each entry has keys ``name``,
    ``enabled``, ``cli_flag``, ``description``, ``prompts``."""
    save_registry(data_dir, [
        Skill(
            name=s["name"],
            enabled=bool(s.get("enabled", True)),
            cli_flag=s.get("cli_flag", f"--skill {s['name']}"),
            description=s.get("description", ""),
            prompts=s.get("prompts", {}),
        )
        for s in skills
    ])