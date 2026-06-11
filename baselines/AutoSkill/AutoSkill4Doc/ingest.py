"""
Document ingestion stage for the offline document pipeline.

This stage turns file or structured input into normalized `DocumentRecord`
objects, computes stable content hashes, and performs incremental skip checks
against the document registry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
import re
import uuid
from typing import Any, Dict, List, Optional, Protocol, Tuple

from autoskill.llm.base import LLM
from autoskill.llm.factory import build_llm

from .core.common import StageLogger, document_progress_label, emit_stage_log, normalize_text
from .core.config import (
    DEFAULT_EXTRACT_STRATEGY,
    DEFAULT_LLM_RATE_LIMIT_REQUESTS,
    DEFAULT_LLM_RATE_LIMIT_WINDOW_S,
    DEFAULT_MAX_SECTION_CHARS,
    DEFAULT_SECTION_OUTLINE_MODE,
    normalize_extract_strategy,
    normalize_section_outline_mode,
)
from .core.llm_utils import llm_complete_json, maybe_json_dict
from .core.rate_limit import AUTOSKILL4DOC_LLM_SCOPE, maybe_wrap_llm_with_rate_limit
from .document.file_loader import data_to_text_unit, load_file_units
from .document.windowing import build_windows_for_record
from .models import DocumentRecord, DocumentSection, StrictWindow, TextSpan, TextUnit
from .store.registry import DocumentRegistry


_MARKDOWN_HEADING_RE = re.compile(r"^\s*(#{1,6})\s+(.+?)\s*$")
_DECIMAL_HEADING_RE = re.compile(r"^\s*(\d+(?:\.\d+){0,4})(?:\s*[.)、])?\s+(.+?)\s*$")
_DECIMAL_INLINE_HEADING_RE = re.compile(r"^\s*(\d+(?:\.\d+){0,4})(?:\s*[.)、])?\s*(.+?)\s*$")
_CHAPTER_HEADING_RE = re.compile(r"^\s*第([一二三四五六七八九十百零〇\d]+)(章|节|部分|篇)\s+(.+?)\s*$")
_CN_ENUM_HEADING_RE = re.compile(r"^\s*([一二三四五六七八九十百零〇]+)[、.]\s*(.+?)\s*$")
_PAREN_ENUM_HEADING_RE = re.compile(r"^\s*[（(]([一二三四五六七八九十百零〇\d]+)[）)]\s*(.+?)\s*$")
_ROMAN_HEADING_RE = re.compile(r"^\s*([IVXLCM]+)[.)]\s+(.+?)\s*$", re.IGNORECASE)
_BULLET_LINE_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
_REFERENCE_LINE_RE = re.compile(
    r"^\s*(?:\[\d+\]|\(\d+\)|\d+\.\s+.+\b(?:19|20)\d{2}[a-z]?\b.+|.+\bdoi\b.+|https?://\S+)",
    re.IGNORECASE,
)
_AUTHOR_HEADING_RE = re.compile(r"^[A-Za-z\u4e00-\u9fff·•\s]+(?:\d+(?:,\d+)*)?$")
_CONTACT_LINE_RE = re.compile(r"\b(?:email|e-mail|received|accepted|published)\b|收稿日期|录用日期|发布日期", re.IGNORECASE)
_NON_CONTENT_HEADING_MARKERS = {
    "abstract",
    "keywords",
    "keyword",
    "summary",
    "摘要",
    "关键词",
}
_TERMINAL_BACKMATTER_MARKERS = (
    "references",
    "reference",
    "bibliography",
    "acknowledg",
    "致谢",
    "参考文献",
    "附录",
)
_OUTLINE_FALLBACK_MAX_CANDIDATES = 64
_OUTLINE_RULE_CANDIDATE_LIMIT = 96


@dataclass(frozen=True)
class _DetectedHeading:
    """One detected section heading with a normalized hierarchy level."""

    start: int
    end: int
    heading: str
    level: int
    number: str = ""
    kind: str = "plain"


def _looks_like_heading_title(title: str, *, allow_sentence_like: bool = False) -> bool:
    """Heuristic guard used to reject numbered list items misread as headings."""

    text = str(title or "").strip()
    if not text:
        return False
    normalized = normalize_text(text, lower=True)
    if normalized in _NON_CONTENT_HEADING_MARKERS:
        return False
    if len(text) > 120:
        return False
    if text.startswith(("-", "*", "•")):
        return False
    if re.search(r"[。！？!?；;]\s*$", text) and not allow_sentence_like:
        return False
    if text.count("。") + text.count(". ") + text.count("；") + text.count(";") >= 2:
        return False
    if len(text.split()) > 24:
        return False
    return True


def _looks_like_front_matter_heading(heading: str, *, preview: str = "") -> bool:
    """Detects title/author/contact-like lines that should not become sections."""

    text = str(heading or "").strip()
    if not text:
        return False
    normalized = normalize_text(text, lower=True)
    if normalized in _NON_CONTENT_HEADING_MARKERS:
        return True
    preview_text = str(preview or "").strip()
    if preview_text and _CONTACT_LINE_RE.search(preview_text):
        return True
    if _AUTHOR_HEADING_RE.fullmatch(text) and len(text) <= 24:
        bare = re.sub(r"[\d,\s·•]", "", text)
        if 2 <= len(bare) <= 12 and (re.search(r"\d", text) or "," in text or "@" in preview_text):
            return True
    return False


def _looks_like_front_matter_body(text: str) -> bool:
    """Detects abstract/keywords/contact front matter before real sections begin."""

    normalized = normalize_text(str(text or ""), lower=True)
    if not normalized:
        return False
    if any(marker in normalized for marker in _NON_CONTENT_HEADING_MARKERS):
        return True
    return bool(_CONTACT_LINE_RE.search(str(text or "")))


def _detect_heading(line: str, *, start: int, end: int) -> Optional[_DetectedHeading]:
    """Detects markdown, numbered, and Chinese section headings in one line."""

    text = str(line or "").strip()
    if not text:
        return None

    def _markdown_numbered_heading(heading_text: str) -> Optional[_DetectedHeading]:
        """Infers subsection hierarchy from numbered markdown headings."""

        chapter_match = _CHAPTER_HEADING_RE.match(heading_text)
        if chapter_match:
            return _DetectedHeading(
                start=start,
                end=end,
                heading=heading_text,
                level=1,
                number=str(chapter_match.group(1) or "").strip(),
                kind="markdown_chapter",
            )

        decimal_match = _DECIMAL_INLINE_HEADING_RE.match(heading_text)
        if decimal_match:
            number = str(decimal_match.group(1) or "").strip()
            title = str(decimal_match.group(2) or "").strip()
            if title and _looks_like_heading_title(title, allow_sentence_like=True):
                return _DetectedHeading(
                    start=start,
                    end=end,
                    heading=heading_text,
                    level=max(1, number.count(".") + 1),
                    number=number,
                    kind="markdown_decimal",
                )
        return None

    match = _MARKDOWN_HEADING_RE.match(text)
    if match:
        heading = str(match.group(2) or "").strip()
        if _looks_like_heading_title(heading, allow_sentence_like=True):
            inferred = _markdown_numbered_heading(heading)
            if inferred is not None:
                return inferred
            return _DetectedHeading(start=start, end=end, heading=heading, level=len(match.group(1)), kind="markdown")

    match = _CHAPTER_HEADING_RE.match(text)
    if match:
        heading = text
        return _DetectedHeading(start=start, end=end, heading=heading, level=1, number=str(match.group(1) or ""), kind="chapter")

    match = _DECIMAL_HEADING_RE.match(text)
    if match:
        number = str(match.group(1) or "").strip()
        title = str(match.group(2) or "").strip()
        if _looks_like_heading_title(title) and ("." in number or len(title) <= 72):
            return _DetectedHeading(
                start=start,
                end=end,
                heading=text,
                level=max(1, number.count(".") + 1),
                number=number,
                kind="decimal",
            )

    match = _PAREN_ENUM_HEADING_RE.match(text)
    if match:
        title = str(match.group(2) or "").strip()
        if _looks_like_heading_title(title):
            number = str(match.group(1) or "").strip()
            level = 3 if re.fullmatch(r"\d+", number) else 2
            return _DetectedHeading(start=start, end=end, heading=text, level=level, number=number, kind="paren")

    match = _CN_ENUM_HEADING_RE.match(text)
    if match:
        title = str(match.group(2) or "").strip()
        if _looks_like_heading_title(title):
            return _DetectedHeading(start=start, end=end, heading=text, level=1, number=str(match.group(1) or ""), kind="cn_enum")

    match = _ROMAN_HEADING_RE.match(text)
    if match:
        title = str(match.group(2) or "").strip()
        if _looks_like_heading_title(title):
            return _DetectedHeading(start=start, end=end, heading=text, level=1, number=str(match.group(1) or ""), kind="roman")

    return None


def _detect_headings(src: str) -> List[_DetectedHeading]:
    """Detects structural headings line-by-line so numbered sub-sections are preserved."""

    matches: List[_DetectedHeading] = []
    cursor = 0
    for line in str(src or "").splitlines(keepends=True):
        start = cursor
        end = cursor + len(line)
        detected = _detect_heading(line, start=start, end=end)
        if detected is not None:
            matches.append(detected)
        cursor = end
    return _normalize_detected_heading_levels(matches)


def _heading_sequence_info(heading: str) -> Dict[str, Any]:
    """Extracts numbering style information from one heading title."""

    text = str(heading or "").strip()
    if not text:
        return {}
    match = _CHAPTER_HEADING_RE.match(text)
    if match:
        return {"style": "chapter", "number": str(match.group(1) or "").strip(), "level": 1}
    match = _DECIMAL_INLINE_HEADING_RE.match(text)
    if match:
        number = str(match.group(1) or "").strip()
        title = str(match.group(2) or "").strip()
        if title and _looks_like_heading_title(title, allow_sentence_like=True):
            return {
                "style": "decimal",
                "number": number,
                "level": max(1, number.count(".") + 1),
                "has_dot": "." in number,
            }
    match = _PAREN_ENUM_HEADING_RE.match(text)
    if match:
        return {"style": "paren", "number": str(match.group(1) or "").strip()}
    match = _CN_ENUM_HEADING_RE.match(text)
    if match:
        return {"style": "cn_enum", "number": str(match.group(1) or "").strip()}
    match = _ROMAN_HEADING_RE.match(text)
    if match:
        return {"style": "roman", "number": str(match.group(1) or "").strip()}
    return {}


def _enum_style_family(style: str, number: str) -> str:
    """Builds a coarse numbering family for matching sibling heading styles."""

    raw_style = str(style or "").strip()
    raw_number = str(number or "").strip()
    if raw_style == "paren":
        return "paren_digit" if re.fullmatch(r"\d+", raw_number) else "paren_cn"
    return raw_style


def _previous_same_style_level(
    *,
    history: Sequence[_DetectedHeading],
    style: str,
    number: str,
) -> int:
    """Finds the most recent same-style heading level for sibling recovery."""

    target_family = _enum_style_family(style, number)
    for previous_heading in reversed(list(history or [])):
        previous_info = _heading_sequence_info(previous_heading.heading)
        previous_style = str(previous_info.get("style") or "").strip()
        previous_number = str(previous_info.get("number") or "").strip()
        if _enum_style_family(previous_style, previous_number) != target_family:
            continue
        level = int(previous_heading.level or 0)
        if level > 0:
            return level
    return 0


def _contextual_heading_level(
    *,
    style: str,
    previous: Optional[_DetectedHeading],
    history: Sequence[_DetectedHeading],
    next_info: Dict[str, Any],
) -> int:
    """Infers levels for ambiguous heading styles using neighboring headings."""

    prev_info = _heading_sequence_info(previous.heading) if previous is not None else {}
    prev_level = int(previous.level or 0) if previous is not None else 0
    prev_style = str(prev_info.get("style") or "").strip()
    next_style = str(next_info.get("style") or "").strip()

    if style == "paren":
        current_number = str(next_info.get("current_number") or "").strip()
        if re.fullmatch(r"\d+", current_number):
            prev_number = str(prev_info.get("number") or "").strip()
            next_number = str(next_info.get("number") or "").strip()
            current_value = int(current_number)
            if prev_style == "paren" and re.fullmatch(r"\d+", prev_number) and abs(current_value - int(prev_number)) <= 1 and prev_level > 0:
                return prev_level
            if prev_style in {"decimal", "chapter"} and prev_level > 0 and current_value <= 4:
                return min(prev_level + 1, 4)
            if next_style == "paren" and re.fullmatch(r"\d+", next_number) and abs(int(next_number) - current_value) == 1 and prev_level > 0:
                return min(prev_level + 1, 4)
            return 0
        sibling_level = _previous_same_style_level(history=history, style=style, number=current_number)
        if sibling_level > 0:
            return sibling_level
        if prev_style == "paren" and prev_level > 0:
            return prev_level
        if prev_level >= 2:
            return min(prev_level + 1, 4)
        return 2

    if style in {"cn_enum", "roman"}:
        sibling_level = _previous_same_style_level(
            history=history,
            style=style,
            number=str(next_info.get("current_number") or "").strip(),
        )
        if sibling_level > 0:
            return sibling_level
        if prev_style == style and prev_level > 0:
            return prev_level
        if prev_level >= 1:
            return min(prev_level + 1, 4)
        if next_style == style:
            return 1
        return 1

    return 1


def _normalize_detected_heading_levels(matches: List[_DetectedHeading]) -> List[_DetectedHeading]:
    """Normalizes raw heading detections using numbering depth and local sequence context."""

    if not matches:
        return []
    normalized: List[_DetectedHeading] = []
    for idx, match in enumerate(list(matches or [])):
        info = _heading_sequence_info(match.heading)
        next_info = _heading_sequence_info(matches[idx + 1].heading) if idx + 1 < len(matches) else {}
        if next_info:
            next_info = {**next_info, "current_number": str(match.number or "").strip()}
        level = int(match.level or 1)
        kind = str(match.kind or "").strip() or "plain"
        number = str(match.number or "").strip()
        style = str(info.get("style") or "").strip()
        if style in {"decimal", "chapter"}:
            has_dot = bool(info.get("has_dot"))
            if style == "decimal" and not has_dot:
                prev_info = _heading_sequence_info(normalized[-1].heading) if normalized else {}
                prev_style = str(prev_info.get("style") or "").strip()
                prev_level = int(normalized[-1].level or 0) if normalized else 0
                prev_number = str(prev_info.get("number") or "").strip()
                previous_root_number = ""
                for previous_heading in reversed(normalized):
                    previous_root_info = _heading_sequence_info(previous_heading.heading)
                    if str(previous_root_info.get("style") or "").strip() != "decimal":
                        continue
                    if bool(previous_root_info.get("has_dot")):
                        continue
                    if int(previous_heading.level or 0) != 1:
                        continue
                    previous_root_number = str(previous_root_info.get("number") or "").strip()
                    break
                if re.fullmatch(r"\d+", number) and re.fullmatch(r"\d+", previous_root_number) and int(number) == int(previous_root_number) + 1:
                    level = 1
                elif prev_style == "decimal" and not bool(prev_info.get("has_dot")) and re.fullmatch(r"\d+", prev_number) and re.fullmatch(r"\d+", number) and abs(int(number) - int(prev_number)) <= 1 and prev_level >= 2:
                    level = prev_level
                elif prev_style == "paren" and prev_level >= 2:
                    level = min(prev_level + 1, 4)
                else:
                    level = int(info.get("level") or level or 1)
            else:
                level = int(info.get("level") or level or 1)
            number = str(info.get("number") or number or "").strip()
            if kind == "markdown":
                kind = f"markdown_{style}"
        elif style in {"paren", "cn_enum", "roman"}:
            level = _contextual_heading_level(
                style=style,
                previous=normalized[-1] if normalized else None,
                history=normalized,
                next_info=next_info,
            )
            number = str(info.get("number") or number or "").strip()
            if kind == "markdown":
                kind = f"markdown_{style}"
        if level <= 0:
            continue
        normalized.append(
            _DetectedHeading(
                start=int(match.start or 0),
                end=int(match.end or 0),
                heading=str(match.heading or "").strip(),
                level=max(1, min(level, 6)),
                number=number,
                kind=kind,
            )
        )
    return normalized


def _first_nonempty_paragraph(text: str, *, limit: int = 180) -> str:
    """Returns a short summary-like snippet from one section body."""

    for piece in re.split(r"\n\s*\n+|\n", str(text or "")):
        normalized = str(piece or "").strip()
        if normalized:
            return normalized[:limit]
    return ""


def _annotate_section_hierarchy(sections: List[DocumentSection]) -> List[DocumentSection]:
    """Adds heading path, parent, and sibling metadata for later window planning."""

    stacks: List[str] = []
    enriched: List[DocumentSection] = []
    raw_paths: List[List[str]] = []
    for section in list(sections or []):
        payload = section.to_dict()
        md = dict(payload.get("metadata") or {})
        existing_path = [str(item).strip() for item in list(md.get("heading_path") or []) if str(item).strip()]
        if existing_path:
            path = existing_path
        else:
            normalized_level = max(1, min(int(section.level or 1), len(stacks) + 1))
            while len(stacks) >= normalized_level:
                stacks.pop()
            stacks.append(section.heading)
            path = list(stacks)
        md["heading_path"] = list(path)
        md["parent_heading"] = path[-2] if len(path) > 1 else ""
        md["section_summary"] = _first_nonempty_paragraph(section.text)
        payload["metadata"] = md
        enriched.append(DocumentSection.from_dict(payload))
        raw_paths.append(path)

    sibling_map: Dict[Tuple[str, ...], List[str]] = {}
    for path in raw_paths:
        sibling_map.setdefault(tuple(path[:-1]), []).append(path[-1])

    final_sections: List[DocumentSection] = []
    for section, path in zip(enriched, raw_paths):
        payload = section.to_dict()
        md = dict(payload.get("metadata") or {})
        siblings = [heading for heading in sibling_map.get(tuple(path[:-1]), []) if heading != section.heading]
        if siblings:
            md["sibling_headings"] = siblings[:8]
        payload["metadata"] = md
        final_sections.append(DocumentSection.from_dict(payload))
    return final_sections


def _fallback_single_section(src: str, *, default_title: str = "") -> List[DocumentSection]:
    """Returns one document-wide section when no structure can be recovered."""

    title = str(default_title or "Document").strip() or "Document"
    return [
        DocumentSection(
            heading=title,
            text=src.strip(),
            level=1,
            span=TextSpan(start=0, end=len(src)),
            metadata={"heading_path": [title]},
        )
    ]


def _build_sections_from_headings(src: str, matches: List[_DetectedHeading], *, default_title: str = "") -> List[DocumentSection]:
    """Builds sections from one ordered heading list."""

    if not matches:
        return _fallback_single_section(src, default_title=default_title)

    out: List[DocumentSection] = []
    first = matches[0]
    if first.start > 0:
        prefix = src[: first.start].strip()
        if prefix and not _looks_like_front_matter_body(prefix):
            overview = str(default_title or "Overview").strip() or "Overview"
            out.append(
                DocumentSection(
                    heading=overview,
                    text=prefix,
                    level=1,
                    span=TextSpan(start=0, end=first.start),
                    metadata={"heading_path": [overview]},
                )
            )

    heading_stack: List[_DetectedHeading] = []
    for idx, match in enumerate(matches):
        while heading_stack and heading_stack[-1].level >= match.level:
            heading_stack.pop()
        heading_stack.append(match)
        content_start = match.end
        content_end = matches[idx + 1].start if idx + 1 < len(matches) else len(src)
        body = src[content_start:content_end].strip()
        if not body:
            continue
        if _looks_like_front_matter_heading(match.heading, preview=body[:240]):
            continue
        path = [item.heading for item in heading_stack]
        out.append(
            DocumentSection(
                heading=str(match.heading or "").strip() or (default_title or "Section"),
                text=body,
                level=int(match.level or 1),
                span=TextSpan(start=content_start, end=content_end),
                metadata={
                    "heading_path": path,
                    "parent_heading": path[-2] if len(path) > 1 else "",
                    "heading_number": str(match.number or "").strip(),
                    "heading_kind": str(match.kind or "").strip(),
                },
            )
        )
    sections = _annotate_section_hierarchy(out) if out else _fallback_single_section(src, default_title=default_title)
    trimmed: List[DocumentSection] = []
    stop_after_backmatter = False
    for section in sections:
        if stop_after_backmatter:
            break
        heading_normalized = normalize_text(section.heading, lower=True)
        if any(marker in heading_normalized for marker in _TERMINAL_BACKMATTER_MARKERS):
            stop_after_backmatter = True
            break
        trimmed.append(section)
    return trimmed or sections


def _iter_line_records(src: str) -> List[Dict[str, Any]]:
    """Returns line records with stable offsets for outline classification."""

    records: List[Dict[str, Any]] = []
    cursor = 0
    for idx, raw_line in enumerate(str(src or "").splitlines(keepends=True)):
        text = raw_line.rstrip("\r\n")
        records.append(
            {
                "line_index": idx,
                "text": text,
                "stripped": text.strip(),
                "start": cursor,
                "end": cursor + len(raw_line),
                "blank": not text.strip(),
            }
        )
        cursor += len(raw_line)
    return records


def _next_nonempty_preview(lines: List[Dict[str, Any]], *, start_index: int, limit: int = 160) -> str:
    """Returns a short preview from the next non-empty paragraph after one heading candidate."""

    snippets: List[str] = []
    for idx in range(start_index + 1, len(lines)):
        text = str(lines[idx].get("stripped") or "").strip()
        if not text:
            if snippets:
                break
            continue
        snippets.append(text)
        if len(" ".join(snippets)) >= limit:
            break
    return " ".join(snippets)[:limit]


def _heading_outline_candidates(src: str) -> List[Dict[str, Any]]:
    """Builds a compact candidate outline for one document-wide LLM fallback pass."""

    lines = _iter_line_records(src)
    candidates: List[Dict[str, Any]] = []
    for idx, record in enumerate(lines):
        stripped = str(record.get("stripped") or "").strip()
        if not stripped:
            continue
        if len(stripped) > 120:
            continue
        if _BULLET_LINE_RE.match(stripped):
            continue
        if _REFERENCE_LINE_RE.search(stripped):
            continue
        if not _looks_like_heading_title(stripped):
            continue
        prev_blank = idx == 0 or bool(lines[idx - 1].get("blank"))
        next_blank = idx + 1 >= len(lines) or bool(lines[idx + 1].get("blank"))
        if not (prev_blank or next_blank):
            continue
        candidates.append(
            {
                "candidate_index": len(candidates),
                "line_index": int(record.get("line_index") or idx),
                "text": stripped,
                "preview": _next_nonempty_preview(lines, start_index=idx),
                "start": int(record.get("start") or 0),
                "end": int(record.get("end") or 0),
            }
        )
        if len(candidates) >= _OUTLINE_FALLBACK_MAX_CANDIDATES:
            break
    return candidates


def _outline_candidates_from_rule_matches(matches: List[_DetectedHeading]) -> List[Dict[str, Any]]:
    """Turns rule-detected headings into one compact LLM candidate list."""

    candidates: List[Dict[str, Any]] = []
    for match in list(matches or [])[:_OUTLINE_RULE_CANDIDATE_LIMIT]:
        candidates.append(
            {
                "candidate_index": len(candidates),
                "line_index": -1,
                "text": str(match.heading or "").strip(),
                "preview": "",
                "start": int(match.start or 0),
                "end": int(match.end or 0),
                "rule_level": int(match.level or 1),
                "rule_kind": str(match.kind or "").strip(),
                "rule_number": str(match.number or "").strip(),
            }
        )
    return candidates


def _merged_outline_candidates(src: str, matches: List[_DetectedHeading]) -> List[Dict[str, Any]]:
    """Builds one deduplicated candidate list from rules first, then heuristics."""

    merged: List[Dict[str, Any]] = []
    seen: set[tuple[int, int, str]] = set()
    for item in list(_outline_candidates_from_rule_matches(matches)) + list(_heading_outline_candidates(src)):
        key = (
            int(item.get("start") or 0),
            int(item.get("end") or 0),
            str(item.get("text") or "").strip(),
        )
        if key in seen:
            continue
        seen.add(key)
        payload = dict(item)
        payload["candidate_index"] = len(merged)
        merged.append(payload)
        if len(merged) >= _OUTLINE_FALLBACK_MAX_CANDIDATES:
            break
    return merged


def _outline_candidate_neighbors(candidates: List[Dict[str, Any]], index: int) -> Tuple[str, str]:
    """Returns neighboring candidate titles for one outline item."""

    previous = ""
    next_text = ""
    if index - 1 >= 0:
        previous = str(candidates[index - 1].get("text") or "").strip()
    if index + 1 < len(candidates):
        next_text = str(candidates[index + 1].get("text") or "").strip()
    return previous, next_text


def _outline_matches_from_llm(
    *,
    src: str,
    default_title: str,
    llm: Optional[LLM],
    rule_matches: Optional[List[_DetectedHeading]] = None,
) -> List[_DetectedHeading]:
    """Runs one compact outline-classification call over heading candidates."""

    if llm is None:
        return []
    candidates = _merged_outline_candidates(src, list(rule_matches or []))
    if len(candidates) < 2:
        return []

    payload = {
        "title": str(default_title or "").strip(),
        "instruction": (
            "Identify only true structural section or subsection headings. "
            "Ignore document titles, author or affiliation lines, abstracts, keywords, references, promotional text, "
            "and numbered procedure/list items unless they clearly start a sustained subsection with its own body."
        ),
        "candidates": [
            {
                "candidate_index": item["candidate_index"],
                "line_index": item["line_index"],
                "text": item["text"],
                "preview": item["preview"],
                "previous_candidate": _outline_candidate_neighbors(candidates, item["candidate_index"])[0],
                "next_candidate": _outline_candidate_neighbors(candidates, item["candidate_index"])[1],
                "rule_hint_level": int(item.get("rule_level") or 0),
                "rule_hint_kind": str(item.get("rule_kind") or "").strip(),
                "rule_hint_number": str(item.get("rule_number") or "").strip(),
            }
            for item in candidates
        ],
    }
    system = (
        "You classify heading candidates for one long document outline.\n"
        "Return JSON only: {\"headings\": [{\"candidate_index\": 0, \"level\": 1}]}\n"
        "Rules:\n"
        "- Include only real structural headings.\n"
        "- level 1 means top-level section, level 2 means subsection, level 3 means sub-subsection.\n"
        "- Use neighboring candidate titles and preview text to infer continuity.\n"
        "- Prefer hierarchy continuity: siblings with the same numbering style usually stay at the same level unless a clear parent heading intervenes.\n"
        "- Prefer broader section headings over short in-body checklist items.\n"
        "- Use rule_hint_level and rule_hint_kind as weak hints only; you may override them when the title sequence indicates a better hierarchy.\n"
        "- Ignore document titles, author names, affiliations, contact/publication metadata, abstract/keywords headings, references, bibliography, acknowledgements, figure/table captions, bullet items, and normal prose lines.\n"
        "- Ignore numbered list or procedure items such as 1., 1), (1), (7) inside a body unless they clearly begin a substantial subsection followed by its own paragraph block.\n"
        "- Prefer fewer but higher-confidence headings over over-segmenting body lists into fake sections.\n"
        "- When two choices are plausible, prefer the shallower level unless there is strong evidence for a deeper subsection.\n"
        "- Use relative levels within this document only.\n"
    )
    repair_system = (
        "Return strict JSON only in the form {\"headings\": [{\"candidate_index\": 0, \"level\": 1}]}. "
        "Do not include explanations."
    )
    try:
        parsed = llm_complete_json(
            llm=llm,
            system=system,
            payload=payload,
            repair_system=repair_system,
            repair_payload=payload,
        )
    except Exception:
        return []

    obj = maybe_json_dict(parsed)
    raw_headings = list(obj.get("headings") or [])
    by_index = {int(item["candidate_index"]): item for item in candidates}
    matches: List[_DetectedHeading] = []
    for raw in raw_headings:
        if not isinstance(raw, dict):
            continue
        try:
            candidate_index = int(raw.get("candidate_index"))
        except Exception:
            continue
        item = by_index.get(candidate_index)
        if item is None:
            continue
        try:
            level = max(1, min(int(raw.get("level") or 1), 4))
        except Exception:
            level = 1
        matches.append(
            _DetectedHeading(
                start=int(item["start"]),
                end=int(item["end"]),
                heading=str(item["text"]).strip(),
                level=level,
                kind="outline_llm",
            )
        )
    return sorted(matches, key=lambda item: (item.start, item.end))


def _should_try_outline_fallback(src: str, matches: List[_DetectedHeading]) -> bool:
    """Returns whether one document has enough heading candidates for one outline pass."""

    if not str(src or "").strip():
        return False
    return len(_merged_outline_candidates(src, matches)) >= 2


def _prefer_outline_matches(
    *,
    src: str,
    rule_matches: List[_DetectedHeading],
    llm_matches: List[_DetectedHeading],
) -> bool:
    """Chooses whether LLM-derived headings look materially better than rule headings."""

    if not llm_matches:
        return False
    if not rule_matches:
        return True
    rule_top_level = sum(1 for item in rule_matches if int(item.level or 1) <= 1)
    llm_top_level = sum(1 for item in llm_matches if int(item.level or 1) <= 1)
    if len(llm_matches) > len(rule_matches):
        return True
    if llm_top_level > rule_top_level:
        return True
    if len(str(src or "")) >= 4000 and len(llm_matches) >= len(rule_matches) and llm_top_level >= rule_top_level:
        return True
    return False


def compute_content_hash(
    *,
    title: str,
    raw_text: str,
    sections: List[DocumentSection],
    metadata: Dict[str, Any],
    authors: List[str],
    year: Optional[int],
    domain: str,
    source_type: str,
) -> str:
    """Builds a stable content hash for incremental detection."""

    payload = {
        "title": str(title or "").strip(),
        "raw_text": str(raw_text or ""),
        "sections": [sec.to_dict() for sec in (sections or [])],
        "metadata": dict(metadata or {}),
        "authors": [str(x).strip() for x in (authors or []) if str(x).strip()],
        "year": int(year) if year is not None else None,
        "domain": str(domain or "").strip(),
        "source_type": str(source_type or "").strip(),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def parse_sections_from_text(text: str, *, default_title: str = "") -> List[DocumentSection]:
    """
    Parses markdown-style sections from text.

    If no headings are present, the whole document is treated as one section.
    """

    src = str(text or "")
    if not src.strip():
        return []

    return _build_sections_from_headings(src, _detect_headings(src), default_title=default_title)


def _normalize_source_type(source_type: str, source_file: str) -> str:
    """Chooses a generic source type with lightweight file-based hints."""

    src = str(source_type or "").strip()
    if src:
        return src
    ext = os.path.splitext(str(source_file or "").strip())[1].lower()
    if ext in {".md", ".markdown"}:
        return "markdown_document"
    if ext in {".txt"}:
        return "text_document"
    if ext in {".json", ".jsonl"}:
        return "structured_document"
    return "document"


def _structured_units_from_data(data: Any, *, title: str = "") -> List[Dict[str, Any]]:
    """Normalizes in-memory structured input into document-like units."""

    if data is None:
        return []

    if isinstance(data, dict):
        for key in ("documents", "items", "records"):
            bucket = data.get(key)
            if isinstance(bucket, list):
                out: List[Dict[str, Any]] = []
                for idx, item in enumerate(bucket):
                    if isinstance(item, dict):
                        unit = dict(item)
                        unit.setdefault("title", str(unit.get("title") or f"inline_data_{idx + 1}"))
                        out.append(unit)
                    else:
                        out.append(data_to_text_unit(item, title=f"inline_data_{idx + 1}"))
                return out
        if any(k in data for k in {"raw_text", "text", "sections", "title"}):
            return [dict(data)]
        return [data_to_text_unit(data, title=str(title or "inline_data"))]

    if isinstance(data, list):
        out = []
        for idx, item in enumerate(data):
            if isinstance(item, dict) and any(k in item for k in {"raw_text", "text", "sections", "title"}):
                unit = dict(item)
                unit.setdefault("title", str(unit.get("title") or f"inline_data_{idx + 1}"))
                out.append(unit)
            else:
                out.append(data_to_text_unit(item, title=f"inline_data_{idx + 1}"))
        return out

    return [data_to_text_unit(data, title=str(title or "inline_data"))]


def _stable_document_id(*, source_key: str, explicit_doc_id: str = "") -> str:
    """Builds a stable document id derived from source identity rather than content."""

    explicit = str(explicit_doc_id or "").strip()
    if explicit:
        return explicit
    key = str(source_key or "").strip() or "document"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"autoskill-document:{key}"))


def _source_key_for_unit(unit: Dict[str, Any], default_title: str) -> str:
    """Chooses a stable identity key for one input unit."""

    source_file = str(unit.get("source_file") or "").strip()
    if source_file:
        return os.path.abspath(os.path.expanduser(source_file))
    title = str(unit.get("title") or "").strip() or str(default_title or "").strip()
    if title:
        return title
    doc_id = str(unit.get("doc_id") or "").strip()
    if doc_id:
        return doc_id
    return "document"


@dataclass
class DocumentIngestResult:
    """Output of the document ingestion stage."""

    text_units: List[TextUnit] = field(default_factory=list)
    documents: List[DocumentRecord] = field(default_factory=list)
    skipped_documents: List[DocumentRecord] = field(default_factory=list)
    windows: List[StrictWindow] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)
    source_file: Optional[str] = None


class DocumentIngestor(Protocol):
    """Pluggable document ingestion interface."""

    def ingest(
        self,
        *,
        data: Optional[Any],
        file_path: str,
        title: str,
        source_type: str,
        domain: str,
        metadata: Optional[Dict[str, Any]],
        registry: Optional[DocumentRegistry],
        continue_on_error: bool,
        dry_run: bool,
        max_documents: int,
        extract_strategy: str,
        logger: StageLogger,
    ) -> DocumentIngestResult:
        """Runs the ingestion stage and returns normalized document records."""


class HeuristicDocumentIngestor:
    """Rule-based document ingestor used by the MVP offline pipeline."""

    def __init__(
        self,
        *,
        llm: Optional[LLM] = None,
        llm_config: Optional[Dict[str, Any]] = None,
        max_section_chars: int = DEFAULT_MAX_SECTION_CHARS,
        outline_fallback_mode: str = DEFAULT_SECTION_OUTLINE_MODE,
        llm_rate_limit_requests: int = DEFAULT_LLM_RATE_LIMIT_REQUESTS,
        llm_rate_limit_window_s: float = DEFAULT_LLM_RATE_LIMIT_WINDOW_S,
    ) -> None:
        """Builds one document ingestor with optional low-frequency outline LLM fallback."""

        self._llm_config = dict(llm_config or {})
        self.llm_rate_limit_requests = max(0, int(llm_rate_limit_requests or 0))
        self.llm_rate_limit_window_s = max(0.0, float(llm_rate_limit_window_s or 0.0))
        self._llm = maybe_wrap_llm_with_rate_limit(
            llm,
            max_requests=self.llm_rate_limit_requests,
            window_s=self.llm_rate_limit_window_s,
            llm_config=self._llm_config,
            scope=AUTOSKILL4DOC_LLM_SCOPE,
        )
        self.max_section_chars = max(1000, int(max_section_chars or _DEFAULT_MAX_SECTION_CHARS))
        self.outline_fallback_mode = normalize_section_outline_mode(outline_fallback_mode)

    def _outline_llm(self) -> Optional[LLM]:
        """Lazily builds the optional outline-classification LLM."""

        if self.outline_fallback_mode == "rule":
            return None
        if self._llm is not None:
            return self._llm
        provider = str(self._llm_config.get("provider") or "").strip().lower()
        if not provider or provider == "mock":
            return None
        self._llm = maybe_wrap_llm_with_rate_limit(
            build_llm(dict(self._llm_config)),
            max_requests=self.llm_rate_limit_requests,
            window_s=self.llm_rate_limit_window_s,
            llm_config=self._llm_config,
            scope=AUTOSKILL4DOC_LLM_SCOPE,
        )
        return self._llm

    def _parse_sections_with_fallback(self, *, raw_text: str, default_title: str, logger: StageLogger) -> List[DocumentSection]:
        """Uses rule-based heading recall, then one outline LLM classification pass by default."""

        src = str(raw_text or "")
        matches = _detect_headings(src)
        llm = self._outline_llm() if _should_try_outline_fallback(src, matches) else None
        if llm is not None:
            llm_matches = _outline_matches_from_llm(
                src=src,
                default_title=default_title,
                llm=llm,
                rule_matches=matches,
            )
            if llm_matches:
                emit_stage_log(
                    logger,
                    f"[ingest_document] outline-llm title={default_title or 'document'} rule_headings={len(matches)} llm_headings={len(llm_matches)}",
                )
                return _build_sections_from_headings(src, llm_matches, default_title=default_title)
        if matches:
            return _build_sections_from_headings(src, matches, default_title=default_title)
        return _fallback_single_section(src, default_title=default_title)

    def ingest(
        self,
        *,
        data: Optional[Any],
        file_path: str,
        title: str,
        source_type: str,
        domain: str,
        metadata: Optional[Dict[str, Any]],
        registry: Optional[DocumentRegistry],
        continue_on_error: bool,
        dry_run: bool,
        max_documents: int,
        extract_strategy: str,
        logger: StageLogger,
    ) -> DocumentIngestResult:
        """Normalizes input into DocumentRecord objects and performs incremental skipping."""

        abs_input = ""
        if data is not None:
            units = _structured_units_from_data(data, title=title)
        elif str(file_path or "").strip():
            units, abs_input = load_file_units(str(file_path), max_files=int(max_documents or 0))
        else:
            raise ValueError("ingest_document requires data or file_path")

        result = DocumentIngestResult(source_file=(abs_input or None))
        if not units and abs_input and os.path.isfile(abs_input):
            message = f"no readable text extracted from file: {abs_input}"
            result.errors.append({"source_file": abs_input, "error": message})
            emit_stage_log(logger, f"[ingest_document] error source_file={abs_input}: {message}")
            if not continue_on_error:
                raise ValueError(message)
            return result
        if not units and abs_input and os.path.isdir(abs_input):
            message = f"no readable text extracted from directory: {abs_input}"
            result.errors.append({"source_file": abs_input, "error": message})
            emit_stage_log(logger, f"[ingest_document] error source_file={abs_input}: {message}")
            if not continue_on_error:
                raise ValueError(message)
            return result
        base_md = dict(metadata or {})

        for idx, unit in enumerate(units):
            try:
                text_unit = self._build_text_unit(
                    unit=unit,
                    default_title=title,
                    source_type=source_type,
                    domain=domain,
                    metadata=base_md,
                )
                result.text_units.append(text_unit)
                built = self._build_record(
                    unit=unit,
                    default_title=title,
                    source_type=source_type,
                    domain=domain,
                    metadata=base_md,
                    logger=logger,
                )
                existing = (
                    registry.find_document_by_content_hash(
                        doc_id=built.doc_id,
                        content_hash=built.content_hash,
                        source_file=str((built.metadata or {}).get("source_file") or ""),
                    )
                    if registry is not None
                    else None
                )
                if existing is not None:
                    result.skipped_documents.append(existing)
                    emit_stage_log(
                        logger,
                        f"[ingest_document] skip unchanged {document_progress_label(doc_id=existing.doc_id, title=existing.title, source_file=str((existing.metadata or {}).get('source_file') or ''))}",
                    )
                    continue
                result.windows.extend(
                    build_windows_for_record(
                        built,
                        strategy=extract_strategy,
                        max_section_chars=self.max_section_chars,
                    )
                )
                result.documents.append(built)
                emit_stage_log(
                    logger,
                    f"[ingest_document] prepared {document_progress_label(doc_id=built.doc_id, title=built.title, source_file=str((built.metadata or {}).get('source_file') or ''))} sections={len(built.sections or [])} windows={len([w for w in result.windows if w.doc_id == built.doc_id])}",
                )
            except Exception as e:
                result.errors.append({"index": idx, "error": str(e)})
                emit_stage_log(logger, f"[ingest_document] error index={idx}: {e}")
                if not continue_on_error:
                    raise
        return result

    def _build_text_unit(
        self,
        *,
        unit: Dict[str, Any],
        default_title: str,
        source_type: str,
        domain: str,
        metadata: Dict[str, Any],
    ) -> TextUnit:
        """Builds one normalized text unit from raw input payload."""

        raw = str(unit.get("raw_text") or unit.get("text") or "").strip()
        title_value = str(unit.get("title") or "").strip() or str(default_title or "").strip() or "document"
        source_file = str(unit.get("source_file") or "").strip()
        md = dict(metadata or {})
        md.update(dict(unit.get("metadata") or {}))
        if source_file:
            md.setdefault("source_file", source_file)
        source_key = _source_key_for_unit(unit, default_title=title_value)
        unit_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"autoskill4doc-unit:{source_key}"))
        return TextUnit(
            unit_id=unit_id,
            title=title_value,
            text=raw,
            source_file=source_file,
            source_type=_normalize_source_type(source_type, source_file),
            domain=str(unit.get("domain") or domain or "").strip(),
            metadata=md,
        )

    def _build_record(
        self,
        *,
        unit: Dict[str, Any],
        default_title: str,
        source_type: str,
        domain: str,
        metadata: Dict[str, Any],
        logger: StageLogger = None,
    ) -> DocumentRecord:
        """Builds one normalized DocumentRecord from a mixed-shape unit."""

        raw = str(unit.get("raw_text") or unit.get("text") or "").strip()
        sections_raw = list(unit.get("sections") or [])
        title_value = str(unit.get("title") or "").strip() or str(default_title or "").strip() or "document"
        source_file = str(unit.get("source_file") or "").strip()
        authors = [str(x).strip() for x in list(unit.get("authors") or []) if str(x).strip()]
        year = unit.get("year")
        doc_domain = str(unit.get("domain") or domain or "").strip()
        md = dict(metadata or {})
        md.update(dict(unit.get("metadata") or {}))
        if source_file:
            md.setdefault("source_file", source_file)

        if sections_raw:
            sections = [
                sec if isinstance(sec, DocumentSection) else DocumentSection.from_dict(dict(sec or {}))
                for sec in sections_raw
            ]
            sections = _annotate_section_hierarchy(sections)
            if not raw:
                raw = "\n\n".join(sec.text for sec in sections if str(sec.text or "").strip())
        else:
            sections = self._parse_sections_with_fallback(raw_text=raw, default_title=title_value, logger=logger)

        normalized_source_type = _normalize_source_type(source_type, source_file)
        content_hash = compute_content_hash(
            title=title_value,
            raw_text=raw,
            sections=sections,
            metadata=md,
            authors=authors,
            year=(int(year) if year is not None and str(year).strip() else None),
            domain=doc_domain,
            source_type=normalized_source_type,
        )

        source_key = _source_key_for_unit(unit, default_title=title_value)
        doc_id = _stable_document_id(
            source_key=source_key,
            explicit_doc_id=str(unit.get("doc_id") or "").strip(),
        )
        return DocumentRecord(
            doc_id=doc_id,
            source_type=normalized_source_type,
            title=title_value,
            authors=authors,
            year=(int(year) if year is not None and str(year).strip() else None),
            domain=doc_domain,
            raw_text=raw,
            sections=sections,
            metadata=md,
            checksum=content_hash,
            content_hash=content_hash,
        )


def ingest_document(
    *,
    data: Optional[Any] = None,
    file_path: str = "",
    title: str = "",
    source_type: str = "document",
    domain: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    registry: Optional[DocumentRegistry] = None,
    ingestor: Optional[DocumentIngestor] = None,
    continue_on_error: bool = True,
    dry_run: bool = False,
    max_documents: int = 0,
    extract_strategy: str = DEFAULT_EXTRACT_STRATEGY,
    logger: StageLogger = None,
) -> DocumentIngestResult:
    """Public functional wrapper for the document ingestion stage."""

    impl = ingestor or HeuristicDocumentIngestor()
    return impl.ingest(
        data=data,
        file_path=file_path,
        title=title,
        source_type=source_type,
        domain=domain,
        metadata=metadata,
        registry=registry,
        continue_on_error=continue_on_error,
        dry_run=bool(dry_run),
        max_documents=int(max_documents or 0),
        extract_strategy=normalize_extract_strategy(extract_strategy),
        logger=logger,
    )
