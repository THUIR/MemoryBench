"""
Offline-only skill instruction normalization helpers.

This module exists so offline extraction can clean legacy model outputs without
changing core autoskill extraction/format code.
"""

from __future__ import annotations

import re
from typing import List
from autoskill.models import SkillExample


def normalize_instruction_body(
    raw: str,
    *,
    skill_name: str = "",
    skill_description: str = "",
) -> str:
    """
    Normalizes one candidate instruction body into a clean SKILL.md body block.

    Strips common legacy wrappers such as:
    - repeated H1 title + description paragraph
    - `## Prompt` / `## Instructions`
    - trailing helper sections like `## Triggers` / `## Tags`
    - while preserving the current offline conversation section layout
    """

    lines = (raw or "").splitlines()
    if not lines:
        return ""

    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1

    if i < len(lines):
        first = lines[i].strip()
        if first.startswith("# "):
            title = first[2:].strip()
            if title and title.lower() == str(skill_name or "").strip().lower():
                i += 1
                while i < len(lines) and not lines[i].strip():
                    i += 1

        if i < len(lines):
            first2 = lines[i].strip()
            desc = str(skill_description or "").strip()
            if first2 and not first2.startswith("#") and desc and first2 == desc:
                i += 1
                while i < len(lines) and not lines[i].strip():
                    i += 1

        if i < len(lines) and lines[i].strip().lower() in {"## prompt", "## instructions"}:
            i += 1
            while i < len(lines) and not lines[i].strip():
                i += 1

    body = "\n".join(lines[i:]).strip()
    body = _strip_auxiliary_sections(body, keep_examples=False)
    body = _normalize_section_layout(body)
    return _dedupe_exact_markdown_blocks(body)


def extract_examples_from_instruction(raw: str) -> List[SkillExample]:
    """
    Extracts `## Examples` blocks from an instruction body.

    This allows offline extraction to carry examples separately so the final
    SKILL.md can be rendered in the standard AutoSkill layout.
    """

    text = str(raw or "")
    if not text.strip():
        return []

    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        heading = line.strip().lower()
        if heading in {"## examples", "# examples", "## 示例", "# 示例", "## 样例", "# 样例"}:
            start = i + 1
            break
    if start is None:
        return []

    block_lines: List[str] = []
    for j in range(start, len(lines)):
        s = lines[j].strip()
        if j > start and s.startswith("#") and s.lower() not in {"### example 1", "### example 2", "### example 3"}:
            break
        block_lines.append(lines[j])
    return _parse_examples_block("\n".join(block_lines))


def _strip_auxiliary_sections(markdown: str, *, keep_examples: bool) -> str:
    """Drops helper metadata sections that do not belong to body instructions."""
    lines = (markdown or "").splitlines()
    if not lines:
        return ""

    aux = {
        "files",
        "triggers",
        "tags",
        "文件",
        "触发词",
        "标签",
    }
    if not keep_examples:
        aux.update({"examples", "示例", "样例"})
    end = len(lines)
    for j, line in enumerate(lines):
        s = line.strip()
        if not s.startswith("#"):
            continue
        heading = re.sub(r"^#+\s*", "", s).strip().lower()
        if heading in aux:
            end = j
            break
    return "\n".join(lines[:end]).strip()


def _dedupe_exact_markdown_blocks(text: str) -> str:
    """Removes exactly repeated markdown blocks while preserving first-seen order."""
    raw = str(text or "").strip()
    if not raw:
        return ""

    lines = raw.splitlines()
    blocks: List[str] = []
    cur: List[str] = []
    heading_re = re.compile(r"^\s{0,3}#{1,3}\s+\S")

    for ln in lines:
        if heading_re.match(ln) and cur:
            blocks.append("\n".join(cur).strip())
            cur = [ln]
        else:
            cur.append(ln)
    if cur:
        blocks.append("\n".join(cur).strip())

    out: List[str] = []
    seen = set()
    for block in blocks:
        key = re.sub(r"\s+", " ", block).strip().lower()
        if not key:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(block)
    return "\n\n".join(out).strip()


def _normalize_section_layout(markdown: str) -> str:
    """
    Normalizes common legacy section headings into the current offline
    conversation target layout.

    Target sections:
    - # Role & Objective
    - # Communication & Style Preferences
    - # Operational Rules & Constraints
    - # Anti-Patterns
    - # Interaction Workflow
    """

    if not str(markdown or "").strip():
        return ""

    sections = _split_top_level_sections(markdown)
    if not sections:
        return markdown.strip()

    merged = []
    seen_order: List[str] = []
    buckets = {}
    for heading, content in sections:
        norm_heading = _normalize_heading_text(heading)
        key = norm_heading.lower()
        if key not in buckets:
            seen_order.append(norm_heading)
            buckets[key] = []
        if str(content or "").strip():
            buckets[key].append(str(content or "").strip())

    for heading in seen_order:
        body = "\n\n".join([x for x in buckets.get(heading.lower(), []) if x.strip()]).strip()
        if not body:
            continue
        merged.append(f"# {heading}\n\n{body}".strip())

    if not merged:
        return markdown.strip()
    return "\n\n".join(merged).strip()


def _split_top_level_sections(markdown: str) -> List[tuple[str, str]]:
    """Splits markdown by `# Heading` top-level sections."""
    lines = (markdown or "").splitlines()
    sections: List[tuple[str, str]] = []
    current_heading = ""
    current_lines: List[str] = []

    def flush() -> None:
        nonlocal current_heading, current_lines
        if current_heading and current_lines:
            sections.append((current_heading, "\n".join(current_lines).strip()))
        current_heading = ""
        current_lines = []

    for line in lines:
        s = line.strip()
        if s.startswith("# ") and not s.startswith("## "):
            flush()
            current_heading = s[2:].strip()
            continue
        if current_heading:
            current_lines.append(line)
    flush()
    return sections


def _normalize_heading_text(heading: str) -> str:
    """Maps common legacy headings to the target offline conversation layout."""
    h = str(heading or "").strip().lower()
    if h in {
        "role & objective",
        "objective",
        "role and objective",
        "purpose",
        "goal",
        "目标",
        "角色与目标",
    }:
        return "Role & Objective"
    if h in {
        "communication & style preferences",
        "style preferences",
        "communication preferences",
        "style",
        "表达偏好",
        "沟通与风格偏好",
        "风格偏好",
    }:
        return "Communication & Style Preferences"
    if h in {
        "operational rules & constraints",
        "rules & constraints",
        "constraints",
        "constraints & style",
        "rules",
        "规则与约束",
        "约束",
        "约束与风格",
        "输出与风格约束",
    }:
        return "Operational Rules & Constraints"
    if h in {
        "anti-patterns",
        "anti patterns",
        "avoid",
        "things to avoid",
        "禁忌",
        "避免事项",
        "反模式",
    }:
        return "Anti-Patterns"
    if h in {
        "interaction workflow",
        "workflow",
        "steps",
        "procedure",
        "流程",
        "工作流",
        "交互流程",
    }:
        return "Interaction Workflow"
    return str(heading or "").strip()


def _parse_examples_block(block: str) -> List[SkillExample]:
    """Best-effort parser for examples written inside offline prompts."""
    lines = str(block or "").splitlines()
    out: List[SkillExample] = []
    cur = {}
    field_name = ""
    field_lines: List[str] = []

    def flush_field() -> None:
        nonlocal field_name, field_lines
        if field_name:
            cur[field_name] = "\n".join(field_lines).strip()
        field_name = ""
        field_lines = []

    def flush_example() -> None:
        flush_field()
        inp = str(cur.get("input") or "").strip()
        if inp:
            out.append(
                SkillExample(
                    input=inp,
                    output=(str(cur.get("output") or "").strip() or None),
                    notes=(str(cur.get("notes") or "").strip() or None),
                )
            )
        cur.clear()

    for ln in lines:
        s = ln.rstrip()
        low = s.strip().lower()
        if low.startswith("### "):
            flush_example()
            continue
        if low in {"input:", "output:", "notes:"}:
            flush_field()
            field_name = low[:-1]
            continue
        if field_name:
            field_lines.append(s)
    flush_example()
    return out[:3]
