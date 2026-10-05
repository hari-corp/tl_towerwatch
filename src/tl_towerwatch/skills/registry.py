from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


# Names of the three prompt slots the app exposes. Order matters: the
# review flow uses ``review`` first, then ``post_review``, then
# ``check_resolved``. The PR detail page renders a tab per slot; the
# CLI ``tl_towerwatch review --slot=<name>`` matches these same names.
PROMPT_SLOTS = ("review", "post_review", "check_resolved")


def _default_prompts() -> dict[str, str]:
    """Built-in prompt templates shipped with the app.

    v1.3.0: collapsed to a single global set — the three prompts apply
    to the whole app, not per-skill. Users edit them in /settings and
    the edits persist to the top-level ``prompts`` block of
    ``config.yaml``. The defaults here ensure a fresh install produces
    useful prompts without forcing the user to type anything.
    """
    return {
        "review": (
            "You are doing a focused code review of PR #{number} in {repo}.\n"
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
            "report for the PR author of #{number} in {repo}. Categorise "
            "each finding (must-fix / nice-to-have / question), drop "
            "duplicates, and write a one-line summary at the top.\n\n"
            "PR title: {title}\n\n"
            "Findings:\n{findings}"
        ),
        "check_resolved": (
            "You are checking whether the author has addressed every review "
            "comment on PR #{number} in {repo}. For each previous finding "
            "below, mark it 'resolved' (the PR addresses it) or 'pending' "
            "(still relevant). If the author added new code that supersedes "
            "the concern, mark it 'resolved' and cite the new commit.\n\n"
            "PR title: {title}\n\n"
            "Previous findings:\n{findings}\n\n"
            "Latest diff (so you can compare to the comments):\n{diff}"
        ),
    }


def load_prompts(data_dir: Path) -> dict[str, str]:
    """Load the global prompts from ``<data_dir>/config.yaml``.

    Returns the built-in defaults when the file doesn't exist yet
    (first-run) or when the ``prompts`` block is missing. Per-slot
    fallback: if a slot is missing or empty in the user's config, we
    fall back to the bundled default — never an empty string — so the
    prompt viewer always renders something.
    """
    cfg = data_dir / "config.yaml"
    if not cfg.exists():
        return _default_prompts()
    try:
        data = yaml.safe_load(cfg.read_text()) or {}
    except Exception:
        return _default_prompts()
    raw = data.get("prompts", {}) if isinstance(data, dict) else {}
    return _coerce_prompts(raw)


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


def save_prompts(data_dir: Path, prompts: dict[str, str]) -> None:
    """Persist the user's prompts to ``<data_dir>/config.yaml``.

    Only the ``prompts`` block is replaced; everything else (theme,
    auth, refresh interval) is preserved. Empty strings clear the slot and
    the next ``load_prompts`` will fall back to the default.
    """
    cfg_path = data_dir / "config.yaml"
    data: dict = {}
    if cfg_path.exists():
        try:
            data = yaml.safe_load(cfg_path.read_text()) or {}
        except Exception:
            data = {}
    block: dict[str, str] = {}
    for slot in PROMPT_SLOTS:
        body = prompts.get(slot, "")
        block[slot] = body if isinstance(body, str) else ""
    data["prompts"] = block
    cfg_path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    )