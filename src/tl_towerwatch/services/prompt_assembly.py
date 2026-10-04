"""Assemble a manual review prompt for a single PR.

v1.3.0 removed all direct LLM integration. tl_towerwatch now just
builds the prompt body the user would otherwise feed to an external
LLM (Claude Code, ChatGPT, etc.). The prompt is rendered by combining
the user's chosen skill's slot template (``review`` / ``post_review`` /
``check_resolved``) with the live PR metadata + diff fetched from
GitHub. The user copies the output, pastes it into their LLM, and
interprets the result themselves.

This module is the single source of truth for that assembly. Both the
``tl_towerwatch review owner/name#N`` CLI command and the
``/pr/.../show-review-prompt`` web route delegate here so the CLI and
web outputs are byte-identical.
"""
from __future__ import annotations

from typing import Iterable
from tl_towerwatch.github.client import GitHubClient
from tl_towerwatch.skills.registry import Skill, load_registry, PROMPT_SLOTS


VALID_SLOTS = PROMPT_SLOTS  # ("review", "post_review", "check_resolved")


def assemble_review_prompt(
    gh: GitHubClient,
    *,
    data_dir,
    owner: str,
    name: str,
    number: int,
    slot: str = "review",
    mode: str = "fresh",
) -> str:
    """Return the rendered prompt body for ``owner/name#number``.

    Loads the enabled skills from ``<data_dir>/config.yaml``, picks
    the ``slot`` template from the FIRST enabled skill (the user can
    re-arrange skills later — for now we render the first match so the
    output is deterministic), fetches the PR metadata + file list
    from GitHub, and runs the template through ``Skill.prompts[slot]``.

    For slots that need a list of prior findings (``post_review``,
    ``check_resolved``), the assistant can't fetch them without
    agent execution — so we emit a friendly placeholder the user fills
    in manually. For the ``review`` slot we splice in the live PR
    description, diff (capped per settings), and head SHA.
    """
    if slot not in VALID_SLOTS:
        raise ValueError(f"unknown prompt slot {slot!r}; must be one of {VALID_SLOTS}")
    skills = [s for s in load_registry(data_dir) if s.enabled]
    if not skills:
        raise ValueError("No enabled skills configured. Visit /settings to enable one.")
    template = _pick_template(skills, slot)
    pr = gh.get_pr(owner, name, number)
    files = gh.list_pr_files(owner, name, number)
    diff_text = _summarize_diff(files, max_files=30, max_lines=2000)
    pr_metadata = {
        "title": pr.title,
        "body": pr.body or "",
        "author": pr.author_login or "",
        "number": pr.number,
        "repo": f"{owner}/{name}",
        "head_sha": pr.head_sha,
        "diff": diff_text,
        "files": _format_file_list(files),
    }
    if slot == "review":
        pr_metadata["mode_intro"] = (
            "This is a FRESH review — ignore any prior context; review only the diff above."
            if mode == "fresh" else
            "This is a COMPARE review — compare against the diff below."
        )
    elif slot == "post_review":
        pr_metadata["findings"] = (
            "<paste the findings your LLM produced here, one per line>"
        )
    elif slot == "check_resolved":
        pr_metadata["findings"] = (
            "<paste the previous findings (one per line) so the LLM can mark each resolved/pending>"
        )
    return _render(template, pr_metadata)


def _pick_template(skills: Iterable[Skill], slot: str) -> str:
    for s in skills:
        body = (s.prompts or {}).get(slot, "")
        if body:
            return body
    # Fall back to the registered slot prompt of the first skill (even
    # if empty) so the caller still gets a string back. The settings
    # page enforces non-empty defaults via _default_prompts().
    return (skills[0].prompts or {}).get(slot, "")


def _summarize_diff(files, *, max_files: int, max_lines: int) -> str:
    """Render a diff snippet the user can paste into their LLM.

    ``files`` is a list of FileData-like objects exposing ``path``,
    ``patch`` and (optionally) ``additions`` / ``deletions`` /
    ``status`` attributes. The output is capped by both file count and
    total line count so a single 5,000-file PR doesn't blow the model's
    context window.
    """
    parts: list[str] = []
    total_lines = 0
    for f in files[:max_files]:
        patch = getattr(f, "patch", None) or ""
        if not patch:
            continue
        path = getattr(f, "path", "?")
        header = f"--- {path} ---\n"
        body_lines = patch.splitlines()
        remaining = max(0, max_lines - total_lines)
        if remaining <= 0:
            break
        body = "\n".join(body_lines[:remaining])
        parts.append(header + body)
        total_lines += len(body_lines[:remaining])
        if total_lines >= max_lines:
            parts.append("... diff truncated for length ...")
            break
    return "\n\n".join(parts)


def _format_file_list(files) -> str:
    """Compact file-list preview for the prompt header."""
    out: list[str] = []
    for f in files[:50]:
        path = getattr(f, "path", "?")
        adds = getattr(f, "additions", None)
        dels = getattr(f, "deletions", None)
        if adds is not None and dels is not None:
            out.append(f"- {path}  (+{adds}/-{dels})")
        else:
            out.append(f"- {path}")
    return "\n".join(out) if out else "(no files)"


def _render(template: str, pr_metadata: dict) -> str:
    try:
        return template.format(**pr_metadata)
    except KeyError as e:
        # The user's template uses a placeholder we don't fill —
        # substitute a clear placeholder so the prompt still works.
        key = e.args[0]
        return template.replace("{" + key + "}", f"<{key} not available>")