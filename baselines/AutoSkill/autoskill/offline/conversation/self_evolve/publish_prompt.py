"""Publish an evolved best prompt into prompts.py builtin specific prompt."""

from __future__ import annotations

import argparse
import ast
import re
from datetime import datetime
from pathlib import Path
from typing import List


TARGET_FUNCTION_NAME = "build_builtin_offline_extract_prompt_specific"
MAX_CANDIDATES_SENTINEL = "__AUTOSKILL_MAX_CANDIDATES__"


def _norm_path(path: str) -> Path:
    return Path(str(path or "")).expanduser().resolve()


def _default_prompts_py_path() -> Path:
    return Path(__file__).resolve().parents[1] / "prompts.py"


def _load_prompt_text(path: Path) -> str:
    if not path.is_file():
        raise SystemExit(f"prompt file not found: {path}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise SystemExit(f"prompt file is empty: {path}")
    return text


def _best_prompt_path_from_run_root(run_root: Path) -> Path:
    path = run_root / "best_prompt.txt"
    if not path.is_file():
        raise SystemExit(f"best_prompt.txt not found under run root: {path}")
    return path


def _prompt_template_from_text(prompt_text: str) -> tuple[str, bool]:
    template, replaced = re.subn(
        r"(with at most )\d+( item\(s\)\.)",
        r"\1" + MAX_CANDIDATES_SENTINEL + r"\2",
        str(prompt_text or ""),
        count=1,
    )
    return template, bool(replaced)


def _escape_for_python(text: str, *, for_fstring: bool) -> str:
    escaped = str(text or "")
    if for_fstring:
        escaped = escaped.replace("{", "{{").replace("}", "}}")
    escaped = (
        escaped.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\t", "\\t")
        .replace("\r", "\\r")
        .replace("\n", "\\n")
    )
    return escaped


def _quote_chunk(chunk: str) -> str:
    text = str(chunk or "")
    if MAX_CANDIDATES_SENTINEL not in text:
        return '"' + _escape_for_python(text, for_fstring=False) + '"'
    if text.count(MAX_CANDIDATES_SENTINEL) != 1:
        raise SystemExit("expected at most one max-candidates placeholder in a single prompt chunk")
    prefix, suffix = text.split(MAX_CANDIDATES_SENTINEL, 1)
    return (
        'f"'
        + _escape_for_python(prefix, for_fstring=True)
        + "{max_candidates}"
        + _escape_for_python(suffix, for_fstring=True)
        + '"'
    )


def _prompt_chunks(prompt_template: str) -> List[str]:
    lines = str(prompt_template or "").splitlines()
    chunks: List[str] = []
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        if line == "":
            idx += 1
            continue
        blank_lines_after = 0
        probe = idx + 1
        while probe < len(lines) and lines[probe] == "":
            blank_lines_after += 1
            probe += 1
        newline_suffix = "\n" * (1 + blank_lines_after)
        chunks.append(line + newline_suffix)
        idx = probe
    return chunks


def _render_target_function(prompt_template: str) -> str:
    body_lines: List[str] = [
        f"def {TARGET_FUNCTION_NAME}(*, channel: str, max_candidates: int) -> str:",
        '    """Run built-in offline extract prompt in specific mode."""',
        "    if not is_offline_channel(channel):",
        '        return ""',
        "    return (",
    ]
    for chunk in _prompt_chunks(prompt_template):
        body_lines.append("        " + _quote_chunk(chunk))
        extra_blank_lines = max(0, chunk.count("\n") - 1)
        for _idx in range(extra_blank_lines):
            body_lines.append("")
    body_lines.append("    )")
    return "\n".join(body_lines) + "\n"


def _replace_target_function(source_text: str, rendered_function: str) -> str:
    module = ast.parse(source_text)
    target = None
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == TARGET_FUNCTION_NAME:
            target = node
            break
    if target is None:
        raise SystemExit(f"function not found in prompts.py: {TARGET_FUNCTION_NAME}")

    lines = source_text.splitlines()
    start = int(target.lineno) - 1
    end = int(target.end_lineno)
    new_lines = lines[:start] + rendered_function.rstrip("\n").splitlines() + lines[end:]
    return "\n".join(new_lines).rstrip() + "\n"


def _backup_path(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return path.with_name(path.name + f".bak.{stamp}")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Write an evolved best prompt into prompts.py builtin specific prompt.",
    )
    source_group = p.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--run-root",
        default="",
        help="Self-evolve run root containing best_prompt.txt.",
    )
    source_group.add_argument(
        "--prompt-file",
        default="",
        help="Direct path to a prompt text file to publish.",
    )
    p.add_argument(
        "--prompts-py",
        default=str(_default_prompts_py_path()),
        help="Target prompts.py path.",
    )
    p.add_argument(
        "--backup",
        default="1",
        help="1|0. Backup prompts.py before overwrite. Default 1.",
    )
    p.add_argument(
        "--dry-run",
        default="0",
        help="1|0. Validate and print summary without writing. Default 0.",
    )
    return p


def main() -> None:
    args = _build_parser().parse_args()
    prompts_py_path = _norm_path(str(args.prompts_py))
    if not prompts_py_path.is_file():
        raise SystemExit(f"prompts.py not found: {prompts_py_path}")

    if str(args.run_root or "").strip():
        source_path = _best_prompt_path_from_run_root(_norm_path(str(args.run_root)))
    else:
        source_path = _norm_path(str(args.prompt_file))

    prompt_text = _load_prompt_text(source_path)
    prompt_template, replaced_dynamic_max = _prompt_template_from_text(prompt_text)
    rendered_function = _render_target_function(prompt_template)
    original_source = prompts_py_path.read_text(encoding="utf-8")
    updated_source = _replace_target_function(original_source, rendered_function)
    compile(updated_source, str(prompts_py_path), "exec")

    dry_run = bool(int(args.dry_run or 0))
    backup_enabled = bool(int(args.backup or 0))
    backup_path = None
    if not dry_run and backup_enabled:
        backup_path = _backup_path(prompts_py_path)
        backup_path.write_text(original_source, encoding="utf-8")
    if not dry_run:
        prompts_py_path.write_text(updated_source, encoding="utf-8")

    print(f"source_prompt: {source_path}", flush=True)
    print(f"target_prompts_py: {prompts_py_path}", flush=True)
    print(f"prompt_chars: {len(prompt_text)}", flush=True)
    print(f"dynamic_max_candidates_replaced: {'yes' if replaced_dynamic_max else 'no'}", flush=True)
    print(f"dry_run: {'yes' if dry_run else 'no'}", flush=True)
    if backup_path is not None:
        print(f"backup_file: {backup_path}", flush=True)


if __name__ == "__main__":
    main()
