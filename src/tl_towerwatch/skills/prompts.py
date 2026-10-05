from __future__ import annotations

from typing import Iterable

# Single combined template we ship as the final fallback. Used when a
# slot's user-edited prompt is empty (the loader falls back to the
# per-slot default before this is ever reached, so it's defensive).
DEFAULT_TEMPLATE = """\
You are reviewing GitHub PR #{number} in repo {repo}.

Title: {title}
Author: {author}
Head SHA: {head_sha}

PR description:
{body}

Diff (truncated):
{diff}

{mode_intro}

Previous findings (file he status from last run):
{findings_list}

Output format:
- After your reasoning, emit a final block delimited by these exact lines:
    <!-- TLTW:FINDINGS -->
    [{{"severity":"high|medium|low","file_path":"...","line":N,"description":"..."}}, ...]
    <!-- TLTW:DONE -->
- Each finding must have a stable `finding_key` derived from file_path:line:slug(description).
"""


def _format_pr_block(pr_metadata: dict) -> dict[str, str]:
    return {
        "title": pr_metadata.get("title", ""),
        "body": pr_metadata.get("body") or "",
        "author": pr_metadata.get("author", ""),
        "number": str(pr_metadata.get("number", "")),
        "repo": pr_metadata.get("repo", ""),
        "head_sha": pr_metadata.get("head_sha", ""),
        "diff": pr_metadata.get("diff", ""),
        "findings": pr_metadata.get("findings", ""),
        "mode_intro": pr_metadata.get("mode_intro", ""),
        "findings_list": pr_metadata.get("findings_list", ""),
    }


def render_prompt(
    template: str,
    *,
    pr_metadata: dict | None = None,
    mode: str = "fresh",
    previous_findings: list[dict] | None = None,
) -> str:
    """Render one prompt template against the assembled PR context.

    ``template`` is the user's edited prompt body. ``pr_metadata``
    provides the static fields (title, body, diff, etc.). ``previous_findings``
    is a convenience input so the caller doesn't have to pre-format the
    findings block for the summary / check-resolved slots.
    """
    meta = dict(pr_metadata or {})
    if previous_findings is not None:
        findings_lines = "\n".join(
            f"- [{f.get('status','?')}] {f.get('severity','?')} "
            f"{f.get('file_path','?')}:{f.get('line','?')} — {f.get('description','')}"
            for f in previous_findings
        ) or "- (none)"
        meta.setdefault("findings_list", findings_lines)
    if "mode_intro" not in meta:
        meta["mode_intro"] = (
            "This is a FRESH review — ignore any prior context; review only the diff above."
            if mode == "fresh" else
            "This is a COMPARE review — for each previous finding, decide if it is still "
            "applicable to the current diff. Mark it `pending` if yes, omit it if it was fixed. "
            "Also flag any new issues."
        )
    try:
        return template.format(**_format_pr_block(meta))
    except KeyError:
        # User-written template uses placeholders we don't fill; fall
        # back to the raw template so we never break the page.
        return template


def render_review_prompt(*, pr_metadata: dict, mode: str,
                         previous_findings: list[dict],
                         diff: str, template: str | None = None) -> str:
    """Backwards-compatible entry point used by callers that already
    have the full PR dict pre-built. New code should call
    ``render_prompt(template, pr_metadata=..., mode=...)``
    directly so the template selection lives in the calling site."""
    return render_prompt(
        template or DEFAULT_TEMPLATE,
        pr_metadata={**pr_metadata, "diff": diff},
        mode=mode,
        previous_findings=previous_findings,
    )