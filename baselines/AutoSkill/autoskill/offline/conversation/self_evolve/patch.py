"""
Prompt patch planning and artifact generation helpers.
"""

from __future__ import annotations

import copy
import difflib
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .artifacts import (
    ROUND_PROMPT_ARTIFACT_SECTIONS,
    _empty_patch_set,
    _ensure_grouped_round_layout,
    _json_dump,
    _load_json,
    _prompt_round_artifact,
    _round_tag,
    _safe_read_text,
)


PATCH_CATEGORIES: Tuple[str, ...] = (
    "add_negative_rules",
    "add_positive_rules",
    "weaken_rules",
    "strengthen_rules",
    "delete_rules",
)
PATCH_PRIORITY: Tuple[str, ...] = (
    "delete_rules",
    "add_negative_rules",
    "strengthen_rules",
    "add_positive_rules",
    "weaken_rules",
)
PROMPT_VISIBLE_PATCH_CATEGORIES: Tuple[str, ...] = (
    "add_negative_rules",
    "add_positive_rules",
    "strengthen_rules",
    "weaken_rules",
    "delete_rules",
)
PATCH_SLOT_HEADING = "### Active Evaluated Patch Rules"
PATCH_SLOT_JSON_MARKER = "### JSON Validity Rules"
_SECTION_HEADING_RE = re.compile(r"^###\s+.+$")
_TOP_LEVEL_LIST_RE = re.compile(r"^(\d+|[A-Z])\.\s+")
_LEGACY_PATCH_SUBHEADING_RE = re.compile(r"^####\s+(.+?)\s*$")
SUPPORTED_PATCH_OPERATIONS = {"insert_rule", "rewrite_rule", "delete_rule", "move_rule"}
SUPPORTED_OPERATION_POSITIONS = {"append", "before_anchor", "after_anchor", "replace"}


def _build_prompt_diff(before: str, after: str) -> str:
    diff = difflib.unified_diff(
        before.splitlines(),
        after.splitlines(),
        fromfile="before",
        tofile="candidate",
        lineterm="",
    )
    body = "\n".join(diff).strip()
    if not body:
        body = "(no diff)"
    return "```diff\n" + body + "\n```\n"


def _dedupe_keep_order(items: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _string_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _normalize_patch_set(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    src = dict(payload or {})
    patch_src = dict(src.get("patch") or {}) if isinstance(src.get("patch"), dict) else src
    out = _empty_patch_set()
    out["accepted_rounds"] = [int(x) for x in list(src.get("accepted_rounds") or []) if str(x).strip()]
    out["operations"] = _normalize_operation_list(patch_src.get("operations"))
    out["_has_native_operations"] = bool(out["operations"])
    key_map = {
        "add_negative_rules": ("add_negative_rules", "must_add_negative_rules"),
        "add_positive_rules": ("add_positive_rules", "must_add_positive_rules"),
        "weaken_rules": ("weaken_rules", "must_weaken_rules"),
        "strengthen_rules": ("strengthen_rules", "must_strengthen_rules"),
        "delete_rules": ("delete_rules", "must_delete_rules"),
    }
    for target, sources in key_map.items():
        items: List[str] = []
        for source in sources:
            items.extend(_string_list(patch_src.get(source)))
        out[target] = _dedupe_keep_order(items)
    if out["operations"]:
        derived = _operations_to_legacy_categories(out["operations"])
        for cat in PATCH_CATEGORIES:
            out[cat] = _dedupe_keep_order(list(out.get(cat) or []) + list(derived.get(cat) or []))
    return out


def _patch_has_content(patch_set: Dict[str, Any]) -> bool:
    normalized = _normalize_patch_set(patch_set)
    return bool(normalized.get("operations")) or any(normalized.get(cat) for cat in PATCH_CATEGORIES)


def _patch_has_prompt_visible_content(patch_set: Dict[str, Any]) -> bool:
    normalized = _normalize_patch_set(patch_set)
    return bool(normalized.get("operations")) or any(normalized.get(cat) for cat in PROMPT_VISIBLE_PATCH_CATEGORIES)


def _base_prompt_length_bounds(base_prompt: str, *, min_ratio: float, max_ratio: float) -> Tuple[int, int]:
    base_len = max(len(str(base_prompt or "").rstrip()), 1)
    min_len = max(1, int(base_len * float(min_ratio)))
    max_len = max(min_len, int(base_len * float(max_ratio)))
    return min_len, max_len


def _within_base_prompt_bounds(prompt_text: str, base_prompt: str, *, min_ratio: float, max_ratio: float) -> bool:
    prompt_len = len(str(prompt_text or "").rstrip())
    min_len, max_len = _base_prompt_length_bounds(base_prompt, min_ratio=min_ratio, max_ratio=max_ratio)
    return min_len <= prompt_len <= max_len


def _naturalize_strengthen_rule(item: str) -> str:
    text = str(item or "").strip()
    if not text:
        return ""
    low = text.lower()
    if low.startswith("strengthen the "):
        return "Apply a stricter reading to the " + text[len("Strengthen the ") :]
    if low.startswith("strengthen "):
        return "Apply a stricter reading to " + text[len("Strengthen ") :]
    return text


def _naturalize_weaken_rule(item: str) -> str:
    text = str(item or "").strip()
    if not text:
        return ""
    low = text.lower()
    if low.startswith("weaken the "):
        return "Allow a softer reading of the " + text[len("Weaken the ") :]
    if low.startswith("weaken "):
        return "Allow a softer reading of " + text[len("Weaken ") :]
    return text


def _section_id_from_heading(heading: str) -> str:
    text = str(heading or "").strip().lower()
    if text == PATCH_SLOT_HEADING.lower():
        return "patch_overlay"
    if "what counts as strong extraction evidence" in text:
        return "positive_rules"
    if "cases that usually still should not be extracted" in text:
        return "negative_cases"
    if "what does not count as a skill" in text:
        return "negative_rules"
    if "task boundary, reusability, and generalization" in text:
        return "generalization"
    if "evidence, provenance, and scope" in text:
        return "evidence_scope"
    if "core principle" in text:
        return "core_principle"
    if "no invention rule" in text:
        return "no_invention"
    if "output construction rules" in text:
        return "output_construction"
    if "confidence guidance" in text:
        return "confidence_guidance"
    if "final emission check" in text:
        return "final_emission_check"
    if "language consistency" in text:
        return "language_consistency"
    if "json validity rules" in text:
        return "json_validity"
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_") or "section"


def _parse_prompt_model(prompt_text: str) -> Dict[str, Any]:
    lines = str(prompt_text or "").rstrip("\n").splitlines()
    preamble: List[str] = []
    sections: List[Dict[str, Any]] = []
    current_heading: Optional[str] = None
    current_lines: List[str] = []

    def _flush() -> None:
        nonlocal current_heading, current_lines
        if current_heading is None:
            return
        sections.append(
            {
                "id": _section_id_from_heading(current_heading),
                "heading": current_heading,
                "lines": list(current_lines),
            }
        )
        current_heading = None
        current_lines = []

    for line in lines:
        if _SECTION_HEADING_RE.match(line.strip()):
            _flush()
            current_heading = line.strip()
            current_lines = []
            continue
        if current_heading is None:
            preamble.append(line)
        else:
            current_lines.append(line)
    _flush()
    sections = [sec for sec in sections if str(sec.get("id") or "") != "patch_overlay"]
    return {"preamble": preamble, "sections": sections}


def _has_legacy_patch_overlay(prompt_text: str) -> bool:
    return PATCH_SLOT_HEADING in str(prompt_text or "")


def _render_prompt_model(model: Dict[str, Any]) -> str:
    parts: List[str] = []
    preamble = "\n".join(list(model.get("preamble") or [])).rstrip()
    if preamble:
        parts.append(preamble)
    for section in list(model.get("sections") or []):
        heading = str(section.get("heading") or "").rstrip()
        body = "\n".join(list(section.get("lines") or [])).rstrip()
        if heading:
            if body:
                parts.append(heading + "\n" + body)
            else:
                parts.append(heading)
    return "\n\n".join(part for part in parts if str(part or "").strip()).rstrip() + "\n"


def _section_text(section: Dict[str, Any]) -> str:
    body = "\n".join(list(section.get("lines") or []))
    return (str(section.get("heading") or "") + "\n" + body).strip()


def _find_section(model: Dict[str, Any], *section_ids: str) -> Optional[Dict[str, Any]]:
    wanted = [str(x or "").strip() for x in section_ids if str(x or "").strip()]
    for sec in list(model.get("sections") or []):
        if str(sec.get("id") or "") in wanted:
            return sec
    return None


def _choose_negative_section(model: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return _find_section(model, "negative_cases", "negative_rules")


def _normalize_operation_item(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    op_name = str(value.get("op") or "").strip()
    if op_name not in SUPPORTED_PATCH_OPERATIONS:
        return None
    target_section = str(value.get("target_section") or "").strip()
    position = str(value.get("position") or "").strip() or "append"
    if position not in SUPPORTED_OPERATION_POSITIONS:
        position = "append"
    anchor_text = str(value.get("anchor_text") or "").strip()
    content = str(value.get("content") or "").strip()
    rationale = str(value.get("rationale") or "").strip()
    if op_name in {"insert_rule", "rewrite_rule", "move_rule"} and not content:
        return None
    if op_name in {"delete_rule", "move_rule"} and not anchor_text:
        return None
    return {
        "op": op_name,
        "target_section": target_section,
        "anchor_text": anchor_text,
        "position": position,
        "content": content,
        "rationale": rationale,
        "priority": _safe_float(value.get("priority"), 0.0),
    }


def _normalize_operation_list(value: Any) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    seen = set()
    if not isinstance(value, list):
        return normalized
    for item in value:
        op = _normalize_operation_item(item)
        if not op:
            continue
        key = (
            str(op.get("op") or ""),
            str(op.get("target_section") or ""),
            str(op.get("anchor_text") or ""),
            str(op.get("position") or ""),
            str(op.get("content") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        normalized.append(op)
    return normalized


def _operations_to_legacy_categories(operations: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {cat: [] for cat in PATCH_CATEGORIES}
    for op in list(operations or []):
        op_name = str(op.get("op") or "").strip()
        target_section = str(op.get("target_section") or "").strip()
        content = str(op.get("content") or "").strip()
        anchor_text = str(op.get("anchor_text") or "").strip()
        if op_name == "insert_rule":
            bucket = "add_positive_rules" if target_section == "positive_rules" else "add_negative_rules"
            if content:
                out[bucket].append(content)
        elif op_name == "rewrite_rule":
            bucket = "strengthen_rules" if target_section not in {"positive_rules"} else "weaken_rules"
            if content:
                out[bucket].append(content)
        elif op_name == "delete_rule":
            if anchor_text:
                out["delete_rules"].append(anchor_text)
    for cat in PATCH_CATEGORIES:
        out[cat] = _dedupe_keep_order(out[cat])
    return out


def _section_ids_for_operation(op: Dict[str, Any], prompt_model: Dict[str, Any]) -> List[str]:
    target_section = str(op.get("target_section") or "").strip()
    if target_section:
        return [target_section]
    content = str(op.get("content") or op.get("anchor_text") or "").strip()
    if not content:
        return ["generalization"]
    return [_infer_best_section_id(prompt_model, content, fallback="generalization")]


def _extract_legacy_overlay_operations(prompt_text: str, prompt_model: Dict[str, Any]) -> List[Dict[str, Any]]:
    lines = str(prompt_text or "").splitlines()
    start_idx = -1
    for idx, line in enumerate(lines):
        if str(line or "").strip() == PATCH_SLOT_HEADING:
            start_idx = idx + 1
            break
    if start_idx < 0:
        return []
    overlay_lines: List[str] = []
    for line in lines[start_idx:]:
        stripped = str(line or "").strip()
        if _SECTION_HEADING_RE.match(stripped):
            break
        overlay_lines.append(line)
    section_map = {
        "Added Negative Rules": ("insert_rule", "negative_cases"),
        "Added Positive Rules": ("insert_rule", "positive_rules"),
        "Strengthened Existing Rules": ("rewrite_rule", "generalization"),
        "Weakened / Clarified Existing Rules": ("rewrite_rule", "generalization"),
        "Deprecated Prior Patch Rules": ("delete_rule", "generalization"),
    }
    current_label = ""
    operations: List[Dict[str, Any]] = []
    for raw_line in overlay_lines:
        stripped = str(raw_line or "").strip()
        if not stripped:
            continue
        m = _LEGACY_PATCH_SUBHEADING_RE.match(stripped)
        if m:
            current_label = str(m.group(1) or "").strip()
            continue
        if not stripped.startswith("- "):
            continue
        item = stripped[2:].strip()
        if not item or item.lower() == "none":
            continue
        op_name, fallback_section = section_map.get(current_label, ("rewrite_rule", "generalization"))
        target_section = _infer_best_section_id(prompt_model, item, fallback=fallback_section)
        if op_name == "insert_rule":
            operations.append(
                {
                    "op": "insert_rule",
                    "target_section": target_section,
                    "anchor_text": "",
                    "position": "append",
                    "content": item,
                    "rationale": "migrated from legacy patch overlay",
                    "priority": 0.5,
                }
            )
        elif op_name == "rewrite_rule":
            content = _naturalize_strengthen_rule(item)
            if current_label == "Weakened / Clarified Existing Rules":
                content = _naturalize_weaken_rule(item)
            operations.append(
                {
                    "op": "rewrite_rule",
                    "target_section": target_section,
                    "anchor_text": "",
                    "position": "append",
                    "content": content,
                    "rationale": "migrated from legacy patch overlay",
                    "priority": 0.5,
                }
            )
        elif op_name == "delete_rule":
            operations.append(
                {
                    "op": "delete_rule",
                    "target_section": target_section,
                    "anchor_text": item,
                    "position": "replace",
                    "content": "",
                    "rationale": "migrated from legacy patch overlay",
                    "priority": 0.5,
                }
            )
    return _normalize_operation_list(operations)


def _normalize_legacy_overlay_prompt(prompt_text: str) -> Dict[str, Any]:
    raw = str(prompt_text or "").rstrip("\n")
    if not raw:
        return {
            "prompt_text": "",
            "had_legacy_overlay": False,
            "migrated_operation_count": 0,
            "migrated_operations": [],
        }
    if not _has_legacy_patch_overlay(raw):
        return {
            "prompt_text": raw + "\n",
            "had_legacy_overlay": False,
            "migrated_operation_count": 0,
            "migrated_operations": [],
        }
    base_model = _parse_prompt_model(raw)
    operations = _extract_legacy_overlay_operations(raw, base_model)
    merged_model = _apply_operations_to_prompt_model(base_model, _normalize_patch_operations({"operations": operations}, base_model))
    normalized_prompt = _render_prompt_model(merged_model)
    return {
        "prompt_text": normalized_prompt,
        "had_legacy_overlay": True,
        "migrated_operation_count": len(operations),
        "migrated_operations": operations,
    }


def _legacy_patch_lists_to_operations(normalized_patch_set: Dict[str, Any], prompt_model: Dict[str, Any]) -> List[Dict[str, Any]]:
    operations: List[Dict[str, Any]] = []
    for item in list(normalized_patch_set.get("add_positive_rules") or []):
        text = str(item or "").strip()
        if text:
            operations.append(
                {
                    "op": "insert_rule",
                    "target_section": "positive_rules",
                    "section_ids": ["positive_rules"],
                    "position": "append",
                    "content": text,
                    "anchor_text": "",
                }
            )
    for item in list(normalized_patch_set.get("add_negative_rules") or []):
        text = str(item or "").strip()
        if text:
            operations.append(
                {
                    "op": "insert_rule",
                    "target_section": "negative_cases",
                    "section_ids": ["negative_cases", "negative_rules"],
                    "position": "append",
                    "content": text,
                    "anchor_text": "",
                }
            )
    for item in list(normalized_patch_set.get("strengthen_rules") or []):
        text = _naturalize_strengthen_rule(item)
        if text:
            target_section = _infer_best_section_id(prompt_model, text, fallback="generalization")
            operations.append(
                {
                    "op": "rewrite_rule",
                    "target_section": target_section,
                    "section_ids": [target_section],
                    "position": "append",
                    "content": text,
                    "anchor_text": "",
                }
            )
    for item in list(normalized_patch_set.get("weaken_rules") or []):
        text = _naturalize_weaken_rule(item)
        if text:
            target_section = _infer_best_section_id(prompt_model, text, fallback="generalization")
            operations.append(
                {
                    "op": "rewrite_rule",
                    "target_section": target_section,
                    "section_ids": [target_section],
                    "position": "append",
                    "content": text,
                    "anchor_text": "",
                }
            )
    for item in list(normalized_patch_set.get("delete_rules") or []):
        text = str(item or "").strip()
        if text:
            target_section = _infer_best_section_id(prompt_model, text, fallback="negative_cases")
            operations.append(
                {
                    "op": "delete_rule",
                    "target_section": target_section,
                    "section_ids": [target_section],
                    "position": "replace",
                    "anchor_text": text,
                    "content": "",
                }
            )
    return operations


def _normalize_patch_operations(normalized_patch_set: Dict[str, Any], prompt_model: Dict[str, Any]) -> List[Dict[str, Any]]:
    normalized_ops = _normalize_operation_list(normalized_patch_set.get("operations"))
    operations: List[Dict[str, Any]] = []
    if normalized_ops:
        for op in normalized_ops:
            bound = dict(op)
            bound["section_ids"] = _section_ids_for_operation(bound, prompt_model)
            operations.append(bound)
    legacy_ops = [] if bool(normalized_patch_set.get("_has_native_operations")) else _legacy_patch_lists_to_operations(normalized_patch_set, prompt_model)
    seen = {
        (
            str(op.get("op") or ""),
            tuple(op.get("section_ids") or []),
            str(op.get("anchor_text") or ""),
            str(op.get("position") or ""),
            str(op.get("content") or ""),
        )
        for op in operations
    }
    for op in legacy_ops:
        key = (
            str(op.get("op") or ""),
            tuple(op.get("section_ids") or []),
            str(op.get("anchor_text") or ""),
            str(op.get("position") or ""),
            str(op.get("content") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        operations.append(op)
    return operations


def _token_set(text: str) -> set[str]:
    return {tok for tok in re.findall(r"[a-z0-9]+", str(text or "").lower()) if tok}


def _infer_best_section_id(prompt_model: Dict[str, Any], text: str, *, fallback: str) -> str:
    needle = str(text or "").strip()
    if not needle:
        return str(fallback or "generalization")
    needle_tokens = _token_set(needle)
    best_id = str(fallback or "generalization")
    best_score = -1.0
    for section in list(prompt_model.get("sections") or []):
        section_id = str(section.get("id") or "")
        if section_id in {"json_validity", "patch_overlay"}:
            continue
        hay = _section_text(section)
        overlap = 0.0
        if needle_tokens:
            hay_tokens = _token_set(hay)
            overlap = len(needle_tokens & hay_tokens) / max(len(needle_tokens), 1)
        sim = difflib.SequenceMatcher(None, needle.lower(), hay.lower()).ratio()
        score = max(sim, overlap)
        if score > best_score:
            best_score = score
            best_id = section_id or best_id
    return best_id


def _contains_rule(section: Dict[str, Any], text: str) -> bool:
    needle = str(text or "").strip().lower()
    if not needle:
        return False
    for line in list(section.get("lines") or []):
        normalized = str(line or "").strip().lower()
        if normalized.endswith(needle) or normalized == needle or normalized == f"- {needle}":
            return True
    return False


def _strip_rule_prefix(text: str) -> str:
    rule = str(text or "").strip()
    if not rule:
        return ""
    while True:
        updated = re.sub(r"^\s*(?:[-*]|(?:\d+[A-Za-z]?|[A-Z])\.)\s+", "", rule).strip()
        if updated == rule:
            return rule
        rule = updated


def _is_list_item_line(line: str) -> bool:
    stripped = str(line or "").strip()
    return bool(_TOP_LEVEL_LIST_RE.match(stripped)) or stripped.startswith("- ")


def _is_indented_list_line(line: str) -> bool:
    raw = str(line or "")
    stripped = raw.strip()
    return bool(raw[: len(raw) - len(raw.lstrip())]) and stripped.startswith("- ")


def _top_level_item_starts(lines: List[str]) -> List[int]:
    starts: List[int] = []
    for idx, line in enumerate(lines):
        if _TOP_LEVEL_LIST_RE.match(str(line or "").strip()):
            starts.append(idx)
    return starts


def _top_level_blocks(section: Dict[str, Any]) -> List[Tuple[int, int, str, str]]:
    lines = list(section.get("lines") or [])
    starts = _top_level_item_starts(lines)
    blocks: List[Tuple[int, int, str, str]] = []
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
        block_lines = lines[start:end]
        stripped = str(lines[start] or "").strip()
        marker_match = _TOP_LEVEL_LIST_RE.match(stripped)
        marker = str(marker_match.group(1) or "") + "." if marker_match else "-"
        blocks.append((start, end, "\n".join(block_lines).strip(), marker))
    return blocks


def _best_anchor_match(section: Dict[str, Any], anchor_text: str) -> Tuple[int, int, int, str, str, float]:
    anchor_low = str(anchor_text or "").strip().lower()
    if not anchor_low:
        return (-1, -1, -1, "", "", 0.0)
    best_idx = -1
    best_score = 0.0
    best_start = -1
    best_end = -1
    best_text = ""
    best_marker = ""
    for idx, (start, end, block_text, marker) in enumerate(_top_level_blocks(section)):
        block_low = block_text.lower()
        score = difflib.SequenceMatcher(None, anchor_low, block_low).ratio()
        if anchor_low in block_low:
            score = max(score, 0.99)
        if score > best_score:
            best_idx = idx
            best_score = score
            best_start = start
            best_end = end
            best_text = block_text
            best_marker = marker
    return (best_idx, best_start, best_end, best_text, best_marker, best_score)


def _section_anchor_score(section: Dict[str, Any], anchor_text: str) -> float:
    return _best_anchor_match(section, anchor_text)[-1]


def _next_list_marker(lines: List[str]) -> str:
    highest_num = 0
    highest_letter = ""
    for line in list(lines or []):
        m = _TOP_LEVEL_LIST_RE.match(str(line or "").strip())
        if not m:
            continue
        token = str(m.group(1) or "")
        if token.isdigit():
            highest_num = max(highest_num, int(token))
        elif len(token) == 1 and token.isalpha():
            highest_letter = max(highest_letter, token.upper())
    if highest_num > 0:
        return f"{highest_num + 1}."
    if highest_letter:
        next_ord = ord(highest_letter) + 1
        if next_ord <= ord("Z"):
            return f"{chr(next_ord)}."
    return "-"


def _find_suffix_start(lines: List[str]) -> int:
    seen_list = False
    last_blank = False
    for idx, line in enumerate(lines):
        stripped = str(line or "").rstrip()
        if _TOP_LEVEL_LIST_RE.match(stripped.strip()):
            seen_list = True
            last_blank = False
            continue
        if not seen_list:
            continue
        if not stripped.strip():
            last_blank = True
            continue
        if not str(line or "").startswith((" ", "\t")) and last_blank:
            return idx
        last_blank = False
    return len(lines)


def _append_rule_to_section(section: Dict[str, Any], text: str) -> None:
    rule = _strip_rule_prefix(text)
    if not rule or _contains_rule(section, rule):
        return
    lines = list(section.get("lines") or [])
    insert_at = _find_suffix_start(lines)
    marker = _next_list_marker(lines)
    new_line = f"{marker} {rule}" if marker != "-" else f"- {rule}"
    prefix = lines[:insert_at]
    suffix = lines[insert_at:]
    if prefix and str(prefix[-1]).strip() and not _is_list_item_line(str(prefix[-1])):
        prefix.append("")
    prefix.append(new_line)
    if suffix and str(suffix[0]).strip() and not _is_list_item_line(str(suffix[0])):
        prefix.append("")
    section["lines"] = prefix + suffix


def _normalize_rule_content_text(text: str) -> str:
    value = str(text or "").strip()
    if "\\n" in value:
        value = value.replace("\\n", "\n")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    return value.strip()


def _rule_content_to_lines(content: str, marker: str) -> List[str]:
    raw = _normalize_rule_content_text(content)
    rule = _strip_rule_prefix(raw)
    if not rule:
        return []
    marker_text = str(marker or "-").strip() or "-"
    if "\n" in rule:
        raw_lines = [line.rstrip() for line in rule.splitlines()]
        first = _strip_rule_prefix(raw_lines[0]) if raw_lines else ""
        out = [f"{marker_text} {first}" if marker_text != "-" else f"- {first}"] if first else []
        for line in raw_lines[1:]:
            stripped = str(line or "").strip()
            if not stripped:
                out.append("")
            elif stripped.startswith("- "):
                out.append(f"   {stripped}" if marker_text != "-" else stripped)
            elif str(line or "").startswith((" ", "\t")):
                out.append(line)
            else:
                out.append(f"   - {stripped}" if marker_text != "-" else f"- {stripped}")
        return out

    parts = [part.strip() for part in re.split(r"\s+-\s+", rule) if part.strip()]
    if len(parts) <= 1:
        return [f"{marker_text} {rule}" if marker_text != "-" else f"- {rule}"]
    first = _strip_rule_prefix(parts[0])
    out = [f"{marker_text} {first}" if marker_text != "-" else f"- {first}"]
    out.extend([f"   - {part}" if marker_text != "-" else f"- {part}" for part in parts[1:]])
    return out


def _append_clarifications_to_section(section: Dict[str, Any], items: List[str]) -> None:
    clarifications = [_strip_rule_prefix(item) for item in items if _strip_rule_prefix(item)]
    if not clarifications:
        return
    lines = list(section.get("lines") or [])
    existing_text = "\n".join(lines)
    new_items = [item for item in clarifications if item.lower() not in existing_text.lower()]
    if not new_items:
        return
    header = "Additional Clarifications:"
    if header in lines:
        header_idx = lines.index(header)
        insert_at = header_idx + 1
        while insert_at < len(lines) and str(lines[insert_at]).startswith("- "):
            insert_at += 1
        lines[insert_at:insert_at] = [f"- {item}" for item in new_items]
    else:
        if lines and str(lines[-1]).strip():
            lines.append("")
        lines.append(header)
        lines.extend([f"- {item}" for item in new_items])
    section["lines"] = lines


def _coalesce_additional_clarifications(section: Dict[str, Any]) -> None:
    lines = list(section.get("lines") or [])
    header = "Additional Clarifications:"
    first_idx = -1
    merged_items: List[str] = []
    kept_lines: List[str] = []
    idx = 0
    while idx < len(lines):
        line = str(lines[idx] or "")
        if line == header:
            if first_idx < 0:
                first_idx = len(kept_lines)
                kept_lines.append(header)
            idx += 1
            while idx < len(lines):
                stripped = str(lines[idx] or "").strip()
                if stripped.startswith("- "):
                    item = stripped[2:].strip()
                    if item and item not in merged_items:
                        merged_items.append(item)
                    idx += 1
                    continue
                if not stripped:
                    idx += 1
                    continue
                break
            continue
        kept_lines.append(line)
        idx += 1
    if first_idx >= 0:
        while kept_lines and not str(kept_lines[-1]).strip():
            kept_lines.pop()
        insert_at = first_idx + 1
        kept_lines[insert_at:insert_at] = [f"- {item}" for item in merged_items]
    section["lines"] = kept_lines


def _compact_top_level_list_spacing(section: Dict[str, Any]) -> None:
    lines = list(section.get("lines") or [])
    compacted: List[str] = []
    for idx, line in enumerate(lines):
        if str(line or "").strip():
            compacted.append(line)
            continue
        prev_nonblank = ""
        for prev in reversed(compacted):
            if str(prev or "").strip():
                prev_nonblank = str(prev)
                break
        next_nonblank = ""
        for nxt in lines[idx + 1 :]:
            if str(nxt or "").strip():
                next_nonblank = str(nxt)
                break
        prev_is_top = bool(_TOP_LEVEL_LIST_RE.match(prev_nonblank.strip()))
        next_is_top = bool(_TOP_LEVEL_LIST_RE.match(next_nonblank.strip()))
        prev_is_indented = _is_indented_list_line(prev_nonblank)
        if next_is_top and (prev_is_top or prev_is_indented):
            continue
        compacted.append(line)
    section["lines"] = compacted


def _renumber_top_level_rules(section: Dict[str, Any]) -> None:
    lines = list(section.get("lines") or [])
    next_num = 1
    for idx, line in enumerate(lines):
        stripped = str(line or "").strip()
        m = _TOP_LEVEL_LIST_RE.match(stripped)
        if not m:
            if stripped and not str(line or "").startswith((" ", "\t")):
                next_num = 1
            continue
        token = str(m.group(1) or "")
        if not token.isdigit():
            continue
        content = re.sub(r"^\s*\d+\.\s+", "", stripped, count=1)
        lines[idx] = f"{next_num}. {content}"
        next_num += 1
    section["lines"] = lines


def _delete_rule_from_section(section: Dict[str, Any], anchor_text: str) -> None:
    anchor = str(anchor_text or "").strip()
    if not anchor:
        return
    lines = list(section.get("lines") or [])
    _best_idx, start, end, _text, _marker, best_score = _best_anchor_match(section, anchor)
    if start < 0 or best_score < 0.45:
        return
    new_lines = lines[:start] + lines[end:]
    while new_lines and not str(new_lines[-1]).strip():
        new_lines.pop()
    section["lines"] = new_lines


def _rewrite_rule_in_section(section: Dict[str, Any], anchor_text: str, content: str) -> bool:
    rule = _strip_rule_prefix(_normalize_rule_content_text(content))
    if not rule:
        return False
    if not anchor_text:
        return False
    lines = list(section.get("lines") or [])
    if not _top_level_item_starts(lines):
        return False
    _best_idx, start, end, _text, marker, best_score = _best_anchor_match(section, anchor_text)
    if start < 0 or best_score < 0.45:
        return False
    new_lines = _rule_content_to_lines(rule, marker)
    if not new_lines:
        return False
    section["lines"] = lines[:start] + new_lines + lines[end:]
    return True


def _insert_rule_relative_to_anchor(
    section: Dict[str, Any],
    *,
    anchor_text: str,
    content: str,
    position: str,
) -> bool:
    rule = _strip_rule_prefix(content)
    anchor = str(anchor_text or "").strip()
    if not rule:
        return False
    if not anchor or position == "append":
        _append_rule_to_section(section, rule)
        return True
    lines = list(section.get("lines") or [])
    if not _top_level_item_starts(lines):
        _append_rule_to_section(section, rule)
        return False
    _best_idx, start, end, _text, marker, best_score = _best_anchor_match(section, anchor)
    if start < 0 or best_score < 0.45:
        _append_rule_to_section(section, rule)
        return False
    insert_at = start if position == "before_anchor" else end
    new_line = f"{marker} {rule}" if marker != "-" else f"- {rule}"
    section["lines"] = lines[:insert_at] + [new_line] + lines[insert_at:]
    return True


def _operation_status(
    op: Dict[str, Any],
    *,
    applied: bool,
    reason: str,
    resolved_section: str = "",
    corrected_target_section: str = "",
) -> Dict[str, Any]:
    return {
        "op": str(op.get("op") or ""),
        "target_section": str(op.get("target_section") or ""),
        "section_ids": list(op.get("section_ids") or []),
        "anchor_text": str(op.get("anchor_text") or ""),
        "position": str(op.get("position") or ""),
        "content": str(op.get("content") or ""),
        "applied": bool(applied),
        "rejected": not bool(applied),
        "reason": str(reason or ""),
        "resolved_section": str(resolved_section or ""),
        "corrected_target_section": str(corrected_target_section or ""),
    }


def _find_unique_anchor_section(
    model: Dict[str, Any],
    anchor_text: str,
    *,
    excluded_section_id: str = "",
) -> Tuple[Optional[Dict[str, Any]], str, str]:
    matches: List[Tuple[str, Dict[str, Any], float]] = []
    for section in list(model.get("sections") or []):
        section_id = str(section.get("id") or "")
        if section_id in {"json_validity", "patch_overlay"} or section_id == excluded_section_id:
            continue
        score = _section_anchor_score(section, anchor_text)
        if score >= 0.45:
            matches.append((section_id, section, score))
    if not matches:
        return None, "", "anchor_not_found_in_prompt"
    matches.sort(key=lambda item: item[2], reverse=True)
    best_section_id, best_section, best_score = matches[0]
    tied = [item for item in matches if abs(item[2] - best_score) < 1e-9 or item[2] >= 0.95]
    tied_ids = {item[0] for item in tied}
    if len(tied_ids) > 1:
        return None, "", "ambiguous_anchor"
    return best_section, best_section_id, "corrected_target_section"


def _resolve_anchor_operation_section(
    model: Dict[str, Any],
    op: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any], Dict[str, Any]]:
    prepared = dict(op)
    target_section_id = str((list(prepared.get("section_ids") or []) or [prepared.get("target_section") or ""])[0] or "")
    target_section = _find_section(model, target_section_id) if target_section_id else None
    anchor_text = str(prepared.get("anchor_text") or "").strip()
    if not anchor_text:
        return None, prepared, _operation_status(
            prepared,
            applied=False,
            reason="missing_anchor_text",
            resolved_section=target_section_id,
        )
    if target_section is not None and _section_anchor_score(target_section, anchor_text) >= 0.45:
        return target_section, prepared, _operation_status(
            prepared,
            applied=True,
            reason="anchor_found_in_target_section",
            resolved_section=target_section_id,
        )
    corrected_section, corrected_section_id, reason = _find_unique_anchor_section(
        model,
        anchor_text,
        excluded_section_id=target_section_id,
    )
    if corrected_section is None:
        return None, prepared, _operation_status(
            prepared,
            applied=False,
            reason=reason if target_section is not None else "target_section_not_found",
            resolved_section=target_section_id,
        )
    original_target = str(prepared.get("target_section") or "")
    prepared["target_section"] = corrected_section_id
    prepared["section_ids"] = [corrected_section_id]
    return corrected_section, prepared, _operation_status(
        prepared,
        applied=True,
        reason=reason,
        resolved_section=corrected_section_id,
        corrected_target_section=corrected_section_id if corrected_section_id != original_target else "",
    )


def _prepare_operation_for_application(
    model: Dict[str, Any],
    op: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    op_name = str(op.get("op") or "").strip()
    if op_name not in {"rewrite_rule", "delete_rule", "move_rule"}:
        return dict(op), _operation_status(op, applied=True, reason="no_anchor_correction_required")
    _section, prepared, status = _resolve_anchor_operation_section(model, op)
    if bool(status.get("applied")):
        return prepared, status
    return None, status


def _apply_operations_to_prompt_model_with_report(
    prompt_model: Dict[str, Any],
    operations: List[Dict[str, Any]],
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    model = copy.deepcopy(prompt_model)
    report: List[Dict[str, Any]] = []
    for op in list(operations or []):
        op_name = str(op.get("op") or "").strip()
        prepared_op, prepare_status = _prepare_operation_for_application(model, op)
        if prepared_op is None:
            report.append(prepare_status)
            continue
        op = prepared_op
        section = _find_section(model, *list(op.get("section_ids") or []))
        if section is None:
            if op_name == "insert_rule":
                section = _choose_negative_section(model) if "negative" in " ".join(list(op.get("section_ids") or [])) else _find_section(model, "generalization")
            elif op_name == "insert_clarification":
                section = _find_section(model, "generalization")
        if section is None:
            report.append(_operation_status(op, applied=False, reason="target_section_not_found"))
            continue
        section_id = str(section.get("id") or "")
        if op_name == "insert_rule":
            before_lines = list(section.get("lines") or [])
            anchor_matched = _insert_rule_relative_to_anchor(
                section,
                anchor_text=str(op.get("anchor_text") or ""),
                content=str(op.get("content") or ""),
                position=str(op.get("position") or "append"),
            )
            applied = before_lines != list(section.get("lines") or [])
            reason = "inserted" if anchor_matched else "insert_anchor_not_found_appended"
            report.append(_operation_status(op, applied=applied, reason=reason if applied else "insert_noop_or_duplicate", resolved_section=section_id))
        elif op_name == "rewrite_rule":
            rewritten = _rewrite_rule_in_section(
                section,
                str(op.get("anchor_text") or ""),
                str(op.get("content") or ""),
            )
            status = dict(prepare_status)
            status.update({"applied": bool(rewritten), "rejected": not bool(rewritten), "reason": status.get("reason") if rewritten else "anchor_not_found", "resolved_section": section_id})
            report.append(status)
        elif op_name == "delete_rule":
            before_lines = list(section.get("lines") or [])
            _delete_rule_from_section(section, str(op.get("anchor_text") or ""))
            applied = before_lines != list(section.get("lines") or [])
            status = dict(prepare_status)
            status.update({"applied": bool(applied), "rejected": not bool(applied), "reason": status.get("reason") if applied else "anchor_not_found", "resolved_section": section_id})
            report.append(status)
        elif op_name == "move_rule":
            anchor_text = str(op.get("anchor_text") or "")
            moved_content = str(op.get("content") or "").strip()
            before_lines = list(section.get("lines") or [])
            _delete_rule_from_section(section, anchor_text)
            target = _find_section(model, *list(op.get("section_ids") or []))
            deleted = before_lines != list(section.get("lines") or [])
            if deleted and target is not None and moved_content:
                _append_rule_to_section(target, moved_content)
            status = dict(prepare_status)
            applied = bool(deleted and target is not None and moved_content)
            status.update({"applied": applied, "rejected": not applied, "reason": status.get("reason") if applied else "move_failed", "resolved_section": section_id})
            report.append(status)
    for section in list(model.get("sections") or []):
        _coalesce_additional_clarifications(section)
        _compact_top_level_list_spacing(section)
        _renumber_top_level_rules(section)
    return model, report


def _apply_operations_to_prompt_model(prompt_model: Dict[str, Any], operations: List[Dict[str, Any]]) -> Dict[str, Any]:
    model, _report = _apply_operations_to_prompt_model_with_report(prompt_model, operations)
    return model


def _replay_operation_status(
    *,
    base_prompt: str,
    patch_set: Dict[str, Any],
    target_op: Dict[str, Any],
) -> Dict[str, Any]:
    prompt_model = _parse_prompt_model(base_prompt)
    operations = _normalize_patch_operations(_normalize_patch_set(patch_set), prompt_model)
    _model, report = _apply_operations_to_prompt_model_with_report(prompt_model, operations)
    target_key = _operation_dedupe_key(target_op)
    fallback: Dict[str, Any] = _operation_status(
        target_op,
        applied=False,
        reason="replay_operation_not_found",
    )
    for op, status in zip(operations, report):
        if _operation_dedupe_key(op) == target_key:
            fallback = status
    if not bool(fallback.get("applied")):
        fallback = dict(fallback)
        fallback["reason"] = str(fallback.get("reason") or "replay_operation_not_applied")
        fallback["replay_rejected"] = True
    return fallback


def _compose_prompt_from_base_and_patch_set(base_prompt: str, patch_set: Dict[str, Any]) -> str:
    base_payload = _normalize_legacy_overlay_prompt(base_prompt)
    normalized_base_prompt = str(base_payload.get("prompt_text") or "").rstrip("\n")
    normalized = _normalize_patch_set(patch_set)
    if not _patch_has_prompt_visible_content(normalized):
        return normalized_base_prompt.rstrip() + "\n"
    prompt_model = _parse_prompt_model(normalized_base_prompt)
    operations = _normalize_patch_operations(normalized, prompt_model)
    if not operations:
        return normalized_base_prompt.rstrip() + "\n"
    merged_model = _apply_operations_to_prompt_model(prompt_model, operations)
    return _render_prompt_model(merged_model)


def _operation_dedupe_key(op: Dict[str, Any]) -> Tuple[str, str, str, str, str]:
    return (
        str(op.get("op") or ""),
        str(op.get("target_section") or ""),
        str(op.get("anchor_text") or ""),
        str(op.get("position") or ""),
        str(op.get("content") or ""),
    )


def _operation_priority_key(op: Dict[str, Any]) -> Tuple[int, float, str]:
    op_name = str(op.get("op") or "").strip()
    target_section = str(op.get("target_section") or "").strip()
    bucket = 99
    if op_name == "delete_rule":
        bucket = 0
    elif op_name == "insert_rule" and target_section in {"negative_cases", "negative_rules"}:
        bucket = 1
    elif op_name == "rewrite_rule":
        bucket = 2
    elif op_name == "insert_rule" and target_section == "positive_rules":
        bucket = 3
    elif op_name == "move_rule":
        bucket = 4
    return (bucket, -_safe_float(op.get("priority"), 0.0), str(op.get("content") or op.get("anchor_text") or ""))


def _merge_patch_set_with_budget(
    *,
    current_patch_set: Dict[str, Any],
    proposal_patch: Dict[str, Any],
    base_prompt: str,
    current_prompt: str,
    round_index: int,
    max_growth_ratio: float,
    base_prompt_min_ratio: float,
    base_prompt_max_ratio: float,
) -> Dict[str, Any]:
    base_prompt = str(_normalize_legacy_overlay_prompt(base_prompt).get("prompt_text") or base_prompt).rstrip("\n")
    current_prompt = str(_normalize_legacy_overlay_prompt(current_prompt).get("prompt_text") or current_prompt).rstrip("\n")
    current = _normalize_patch_set(current_patch_set)
    proposal = _normalize_patch_set(proposal_patch)
    candidate = copy.deepcopy(current)
    accepted_ops: List[Dict[str, Any]] = []
    rejected_ops: List[Dict[str, Any]] = []
    current_prompt_model = _parse_prompt_model(current_prompt)

    current_len = max(len(current_prompt), 1)
    min_len, max_len = _base_prompt_length_bounds(
        base_prompt,
        min_ratio=base_prompt_min_ratio,
        max_ratio=base_prompt_max_ratio,
    )

    def _within_budget(test_patch_set: Dict[str, Any]) -> bool:
        test_prompt = _compose_prompt_from_base_and_patch_set(base_prompt, test_patch_set)
        if not _within_base_prompt_bounds(
            test_prompt,
            base_prompt,
            min_ratio=base_prompt_min_ratio,
            max_ratio=base_prompt_max_ratio,
        ):
            return False
        ratio = abs(len(test_prompt) - len(current_prompt)) / current_len
        return ratio <= float(max_growth_ratio)

    existing_keys = {_operation_dedupe_key(op) for op in _normalize_patch_operations(candidate, current_prompt_model)}
    proposal_ops = sorted(_normalize_patch_operations(proposal, current_prompt_model), key=_operation_priority_key)
    for op in proposal_ops:
        prepared_op, prepare_status = _prepare_operation_for_application(current_prompt_model, op)
        if prepared_op is None:
            rejected = dict(op)
            rejected["application"] = prepare_status
            rejected_ops.append(rejected)
            continue
        op = prepared_op
        key = _operation_dedupe_key(op)
        if key in existing_keys:
            continue
        trial = copy.deepcopy(candidate)
        trial["operations"] = list(trial.get("operations") or []) + [op]
        replay_status = _replay_operation_status(
            base_prompt=base_prompt,
            patch_set=trial,
            target_op=op,
        )
        if not bool(replay_status.get("applied")):
            rejected = dict(op)
            rejected["current_prompt_application"] = prepare_status
            rejected["application"] = replay_status
            rejected_ops.append(rejected)
            continue
        if _within_budget(trial):
            candidate = trial
            existing_keys.add(key)
            accepted = dict(op)
            accepted["application"] = prepare_status
            accepted["replay_application"] = replay_status
            accepted_ops.append(accepted)
        else:
            rejected = dict(op)
            rejected["application"] = _operation_status(op, applied=False, reason="budget_or_length_gate_rejected")
            rejected["current_prompt_application"] = prepare_status
            rejected["replay_application"] = replay_status
            rejected_ops.append(rejected)

    changed = bool(accepted_ops)
    accepted_rounds = [int(x) for x in list(candidate.get("accepted_rounds") or []) if str(x).strip()]
    if changed and int(round_index) not in accepted_rounds:
        accepted_rounds.append(int(round_index))
    candidate["accepted_rounds"] = accepted_rounds
    candidate = _normalize_patch_set(candidate)
    candidate_prompt = _compose_prompt_from_base_and_patch_set(base_prompt, candidate)
    within_length_bounds = _within_base_prompt_bounds(
        candidate_prompt,
        base_prompt,
        min_ratio=base_prompt_min_ratio,
        max_ratio=base_prompt_max_ratio,
    )
    return {
        "patch_set": candidate,
        "accepted_patch": {"operations": accepted_ops},
        "rejected_patch": {"operations": rejected_ops},
        "budget": {
            "max_growth_ratio": float(max_growth_ratio),
            "base_prompt_min_ratio": float(base_prompt_min_ratio),
            "base_prompt_max_ratio": float(base_prompt_max_ratio),
            "base_prompt_char_count": len(str(base_prompt or "").rstrip()),
            "base_prompt_min_char_count": min_len,
            "base_prompt_max_char_count": max_len,
            "current_prompt_char_count": len(current_prompt),
            "candidate_prompt_char_count": len(candidate_prompt),
            "delta_ratio": abs(len(candidate_prompt) - len(current_prompt)) / current_len,
            "within_base_prompt_length_bounds": bool(within_length_bounds),
        },
        "candidate_prompt": candidate_prompt,
    }


def _build_prompt_patch_payload(
    *,
    round_index: int,
    before_prompt: str,
    candidate_prompt: str,
    reflection_output: Dict[str, Any],
) -> Dict[str, Any]:
    normalized_patch = _normalize_patch_set(reflection_output)
    before_model = _parse_prompt_model(before_prompt)
    operations = _normalize_patch_operations(normalized_patch, before_model)
    _validated_model, validation_report = _apply_operations_to_prompt_model_with_report(before_model, operations)
    annotated_operations: List[Dict[str, Any]] = []
    for idx, op in enumerate(operations):
        annotated = dict(op)
        status = validation_report[idx] if idx < len(validation_report) else None
        if status is not None:
            annotated["application"] = status
        annotated_operations.append(annotated)
    op_counts = {
        "insert_rule": 0,
        "rewrite_rule": 0,
        "delete_rule": 0,
        "move_rule": 0,
    }
    for op in operations:
        op_name = str(op.get("op") or "").strip()
        if op_name in op_counts:
            op_counts[op_name] += 1
    return {
        "type": "prompt_patch",
        "round": int(round_index),
        "round_tag": _round_tag(round_index),
        "status": "ready" if (_patch_has_content(normalized_patch) or candidate_prompt.strip()) else "invalid",
        "summary": {
            "operation_count": len(operations),
            "insert_rule_count": int(op_counts["insert_rule"]),
            "rewrite_rule_count": int(op_counts["rewrite_rule"]),
            "delete_rule_count": int(op_counts["delete_rule"]),
            "move_rule_count": int(op_counts["move_rule"]),
            "applied_operation_count": sum(1 for item in validation_report if bool(item.get("applied"))),
            "rejected_operation_count": sum(1 for item in validation_report if bool(item.get("rejected"))),
            "corrected_target_section_count": sum(1 for item in validation_report if str(item.get("corrected_target_section") or "").strip()),
        },
        "rationale": {
            "yn_root_causes": _string_list(reflection_output.get("yn_root_causes")),
            "ny_root_causes": _string_list(reflection_output.get("ny_root_causes")),
            "fp_patterns": _string_list(reflection_output.get("fp_patterns")),
            "fn_patterns": _string_list(reflection_output.get("fn_patterns")),
        },
        "strategy": dict(reflection_output.get("patch_strategy") or {}) if isinstance(reflection_output.get("patch_strategy"), dict) else {},
        "patch": {
            "operations": annotated_operations,
            "application_report": validation_report,
        },
        "prompt_stats": {
            "before_char_count": len(before_prompt),
            "candidate_char_count": len(candidate_prompt),
        },
    }


def _render_prompt_patch_markdown(payload: Dict[str, Any]) -> str:
    patch = dict(payload.get("patch") or {})
    rationale = dict(payload.get("rationale") or {})
    operations = list(patch.get("operations") or [])

    def _render_section(title: str, items: List[str]) -> List[str]:
        lines = [f"## {title}"]
        if items:
            lines.extend([f"- {item}" for item in items])
        else:
            lines.append("- None")
        return lines

    lines: List[str] = [
        f"# Prompt Patch {_round_tag(int(payload.get('round', 0) or 0))}",
        "",
        "This file summarizes the explicit rule patch derived from the reflection output for manual review.",
        "",
    ]
    lines.extend(_render_section("YN Root Causes", _string_list(rationale.get("yn_root_causes"))))
    lines.append("")
    lines.extend(_render_section("NY Root Causes", _string_list(rationale.get("ny_root_causes"))))
    lines.append("")
    lines.extend(_render_section("False Positive Patterns", _string_list(rationale.get("fp_patterns"))))
    lines.append("")
    lines.extend(_render_section("False Negative Patterns", _string_list(rationale.get("fn_patterns"))))
    lines.append("")
    lines.append("## Patch Operations")
    if operations:
        for op in operations:
            op_name = str(op.get("op") or "").strip()
            target_section = str(op.get("target_section") or "").strip() or "generalization"
            anchor_text = str(op.get("anchor_text") or "").strip()
            content = str(op.get("content") or "").strip()
            rationale_text = str(op.get("rationale") or "").strip()
            application = dict(op.get("application") or {})
            priority = _safe_float(op.get("priority"), 0.0)
            line = f"- `{op_name}` -> `{target_section}`"
            if anchor_text:
                line += f" | anchor: {anchor_text}"
            if application:
                line += f" | applied: {bool(application.get('applied'))}"
                if application.get("corrected_target_section"):
                    line += f" | corrected_target_section: {application.get('corrected_target_section')}"
                if application.get("reason"):
                    line += f" | apply_reason: {application.get('reason')}"
            if content:
                line += f" | content: {content}"
            if rationale_text:
                line += f" | rationale: {rationale_text}"
            if priority:
                line += f" | priority: {priority:.2f}"
            lines.append(line)
    else:
        lines.append("- None")
    lines.append("")
    summary = dict(payload.get("summary") or {})
    lines.extend(
        [
            "## Patch Counts",
            f"- operation_count: {int(summary.get('operation_count', 0) or 0)}",
            f"- insert_rule_count: {int(summary.get('insert_rule_count', 0) or 0)}",
            f"- rewrite_rule_count: {int(summary.get('rewrite_rule_count', 0) or 0)}",
            f"- delete_rule_count: {int(summary.get('delete_rule_count', 0) or 0)}",
            f"- move_rule_count: {int(summary.get('move_rule_count', 0) or 0)}",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _write_prompt_patch_artifacts(
    *,
    round_dir: Path,
    round_index: int,
    before_prompt: str,
    candidate_prompt: str,
    reflection_output: Dict[str, Any],
) -> None:
    payload = _build_prompt_patch_payload(
        round_index=round_index,
        before_prompt=before_prompt,
        candidate_prompt=candidate_prompt,
        reflection_output=reflection_output,
    )
    patch_json_path = _prompt_round_artifact(round_dir, "prompt_patch.json")
    patch_md_path = _prompt_round_artifact(round_dir, "prompt_patch.md")
    _json_dump(patch_json_path, payload)
    patch_md_path.parent.mkdir(parents=True, exist_ok=True)
    patch_md_path.write_text(_render_prompt_patch_markdown(payload), encoding="utf-8")


def _backfill_prompt_patch_artifacts(prompt_root: Path) -> None:
    for round_dir in sorted(p for p in prompt_root.glob("round_*") if p.is_dir()):
        _ensure_grouped_round_layout(round_dir, section_map=ROUND_PROMPT_ARTIFACT_SECTIONS)
        reflection_output_path = _prompt_round_artifact(round_dir, "reflection_output.json")
        if not reflection_output_path.is_file():
            continue
        patch_json = _prompt_round_artifact(round_dir, "prompt_patch.json")
        patch_md = _prompt_round_artifact(round_dir, "prompt_patch.md")
        if patch_json.is_file() and patch_md.is_file():
            continue
        reflection_output = _load_json(reflection_output_path)
        candidate_prompt = _safe_read_text(_prompt_round_artifact(round_dir, "prompt_candidate.txt")).rstrip("\n")
        before_prompt = _safe_read_text(_prompt_round_artifact(round_dir, "prompt_before.txt")).rstrip("\n")
        try:
            round_index = int(round_dir.name.split("_")[-1])
        except Exception:
            continue
        _write_prompt_patch_artifacts(
            round_dir=round_dir,
            round_index=round_index,
            before_prompt=before_prompt,
            candidate_prompt=candidate_prompt,
            reflection_output=reflection_output,
        )
