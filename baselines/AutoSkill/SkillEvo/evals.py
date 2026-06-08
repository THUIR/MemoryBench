from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import json
import re

from autoskill.offline.conversation.requirement_memory import requirement_stats_path

from .config import SkillEvoConfig
from .models import EvalRule, LineageRecord, ReplaySample, RuleOutcome, SkillSnapshot


_RE_URL = re.compile(r"https?://\S+")
_RE_MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\((https?://[^)]+)\)")
_RE_SOURCE_LABEL = re.compile(r"(?im)^\s*(来源|参考|source|sources)\s*[:：]")
_RE_JSON_PREFIX = re.compile(r"^\s*[\{\[]")
_RE_CONCLUSION = re.compile(r"(?i)\b(tl;dr|answer|conclusion|bottom line)\b|结论|先说结论")
_RE_PARAGRAPH_LIMIT = re.compile(r"(不超过|少于|最多|within|less than|at most)\s*(\d+)\s*(段|paragraph)")


class EvalCompiler:
    def __init__(self, *, config: SkillEvoConfig, sdk: Any) -> None:
        self.config = config
        self.sdk = sdk

    def compile(
        self,
        *,
        skill: SkillSnapshot,
        lineage: LineageRecord,
    ) -> List[EvalRule]:
        rules: List[EvalRule] = []
        rules.append(
            EvalRule(
                rule_id="response_nonempty",
                label="Non-empty response",
                kind="programmatic",
                scope="response",
                hard=True,
                description="Response must not be empty.",
                params={"mode": "nonempty"},
                provenance={"source": "baseline"},
            )
        )

        corpus = "\n".join(
            [skill.name, skill.description, skill.instructions, "\n".join(skill.tags), "\n".join(skill.triggers)]
        )
        req_texts = self._load_requirement_texts(
            user_id=lineage.user_id,
            offline_lineage_key=lineage.offline_lineage_key,
        )
        if req_texts:
            corpus = corpus + "\n" + "\n".join(req_texts)

        if self._mentions_sources(corpus):
            rules.append(
                EvalRule(
                    rule_id="must_cite_sources",
                    label="Cite sources",
                    kind="programmatic",
                    scope="response",
                    hard=True,
                    description="Response should include explicit sources or links.",
                    params={"mode": "mentions_sources"},
                    provenance={"source": "heuristic"},
                )
            )

        para_limit = self._paragraph_limit(corpus)
        if para_limit:
            rules.append(
                EvalRule(
                    rule_id="paragraph_limit",
                    label=f"At most {para_limit} paragraphs",
                    kind="programmatic",
                    scope="response",
                    hard=True,
                    description="Response should stay within the requested paragraph limit.",
                    params={"mode": "max_paragraphs", "max_paragraphs": int(para_limit)},
                    provenance={"source": "heuristic"},
                )
            )

        if self._mentions_conclusion_first(corpus):
            rules.append(
                EvalRule(
                    rule_id="lead_with_conclusion",
                    label="Lead with the conclusion",
                    kind="programmatic",
                    scope="response",
                    hard=False,
                    description="Response should put the conclusion or direct answer first.",
                    params={"mode": "lead_with_conclusion"},
                    provenance={"source": "heuristic"},
                )
            )

        if self._mentions_json(corpus):
            rules.append(
                EvalRule(
                    rule_id="json_parseable",
                    label="Valid JSON output",
                    kind="programmatic",
                    scope="response",
                    hard=True,
                    description="Response should be valid JSON.",
                    params={"mode": "json_parseable"},
                    provenance={"source": "heuristic"},
                )
            )

        if self._mentions_markdown_table(corpus):
            rules.append(
                EvalRule(
                    rule_id="markdown_table",
                    label="Markdown table present",
                    kind="programmatic",
                    scope="response",
                    hard=False,
                    description="Response should include a markdown table when requested.",
                    params={"mode": "markdown_table"},
                    provenance={"source": "heuristic"},
                )
            )

        if self._mentions_no_hallucination(corpus):
            rules.append(
                EvalRule(
                    rule_id="no_unfounded_claims",
                    label="Avoid unfounded claims",
                    kind="llm_binary",
                    scope="response",
                    hard=True,
                    description="Response should avoid claims not grounded in the request or clearly mark uncertainty.",
                    params={"mode": "requirement", "requirement_text": "Avoid unfounded claims and state uncertainty when needed."},
                    provenance={"source": "heuristic"},
                )
            )

        for requirement in req_texts:
            if len(rules) >= self.config.max_eval_rules:
                break
            if self._redundant_requirement(requirement, rules):
                continue
            rules.append(
                EvalRule(
                    rule_id=f"req_{len(rules) + 1}",
                    label="Requirement satisfaction",
                    kind="llm_binary",
                    scope="response",
                    hard=False,
                    description="Response should satisfy one durable lineage requirement.",
                    params={"mode": "requirement", "requirement_text": requirement},
                    provenance={"source": "offline_requirement_stats"},
                )
            )

        return rules[: self.config.max_eval_rules]

    def _load_requirement_texts(self, *, user_id: str, offline_lineage_key: str) -> List[str]:
        if not offline_lineage_key:
            return []
        path = Path(requirement_stats_path(sdk=self.sdk, user_id=user_id))
        if not path.is_file():
            return []
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        lineages = dict(obj.get("lineages") or {})
        lineage = dict(lineages.get(str(offline_lineage_key)) or {})
        reqs = dict(lineage.get("requirements") or {})
        ranked: List[Tuple[float, str]] = []
        for item in reqs.values():
            if not isinstance(item, dict):
                continue
            canonical = str(item.get("canonical") or "").strip()
            if not canonical:
                continue
            mentions = int(item.get("mentions", 0) or 0)
            hard_mentions = int(item.get("hard_mentions", 0) or 0)
            score = float(mentions) + 0.5 * float(hard_mentions)
            ranked.append((score, canonical))
        ranked.sort(key=lambda x: x[0], reverse=True)
        out: List[str] = []
        seen = set()
        for _score, text in ranked:
            key = self._normalize_text(text)
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(text)
            if len(out) >= 4:
                break
        return out

    def _redundant_requirement(self, requirement: str, rules: List[EvalRule]) -> bool:
        req_key = self._normalize_text(requirement)
        if not req_key:
            return True
        for rule in rules:
            desc = " ".join(
                [
                    str(rule.label or ""),
                    str(rule.description or ""),
                    str(rule.params.get("requirement_text") or ""),
                ]
            )
            if req_key and req_key in self._normalize_text(desc):
                return True
        return False

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", str(text or "").strip().lower())

    def _mentions_sources(self, text: str) -> bool:
        low = self._normalize_text(text)
        return any(
            key in low
            for key in (
                "引用来源",
                "标注来源",
                "注明来源",
                "cite sources",
                "with sources",
                "provide sources",
                "source-backed",
            )
        )

    def _mentions_conclusion_first(self, text: str) -> bool:
        low = self._normalize_text(text)
        return any(
            key in low
            for key in (
                "先给结论",
                "结论在前",
                "先说结论",
                "answer first",
                "lead with the conclusion",
                "bottom line first",
            )
        )

    def _paragraph_limit(self, text: str) -> int:
        for match in _RE_PARAGRAPH_LIMIT.finditer(str(text or "")):
            try:
                return max(1, int(match.group(2)))
            except Exception:
                continue
        low = self._normalize_text(text)
        if "少于 3 段" in low or "不超过 3 段" in low or "3 paragraphs" in low:
            return 3
        return 0

    def _mentions_json(self, text: str) -> bool:
        low = self._normalize_text(text)
        return "json" in low or "结构化输出" in low

    def _mentions_markdown_table(self, text: str) -> bool:
        low = self._normalize_text(text)
        return "markdown table" in low or "表格" in low

    def _mentions_no_hallucination(self, text: str) -> bool:
        low = self._normalize_text(text)
        return any(
            key in low
            for key in (
                "不要幻觉",
                "不要编造",
                "不确定就说",
                "don't hallucinate",
                "do not hallucinate",
                "if unsure",
                "avoid hallucination",
            )
        )


class RuleEngine:
    def __init__(self, *, judge_llm: Any = None) -> None:
        self.judge_llm = judge_llm

    def evaluate(
        self,
        *,
        rule: EvalRule,
        response_text: str,
        sample: ReplaySample,
        variant: SkillSnapshot,
    ) -> RuleOutcome:
        mode = str(rule.params.get("mode") or "").strip()
        if rule.kind == "programmatic":
            passed, details = self._evaluate_programmatic(mode=mode, response_text=response_text, params=dict(rule.params or {}))
        elif rule.kind == "llm_binary":
            passed, details = self._evaluate_llm_binary(rule=rule, response_text=response_text, sample=sample, variant=variant)
        else:
            passed, details = False, {"error": f"unsupported rule kind: {rule.kind}"}
        score = 0.0
        if passed:
            score = 2.0 if rule.hard else 1.0
        return RuleOutcome(
            rule_id=rule.rule_id,
            passed=bool(passed),
            hard=bool(rule.hard),
            score=float(score),
            details=dict(details or {}),
        )

    def _evaluate_programmatic(
        self,
        *,
        mode: str,
        response_text: str,
        params: Dict[str, Any],
    ) -> Tuple[bool, Dict[str, Any]]:
        text = str(response_text or "")
        stripped = text.strip()
        if mode == "nonempty":
            return bool(stripped), {"length": len(stripped)}
        if mode == "json_parseable":
            if not _RE_JSON_PREFIX.search(stripped):
                return False, {"reason": "missing_json_prefix"}
            try:
                json.loads(stripped)
                return True, {}
            except Exception as e:
                return False, {"reason": "json_parse_failed", "error": str(e)}
        if mode == "mentions_sources":
            passed = bool(_RE_URL.search(text) or _RE_MARKDOWN_LINK.search(text) or _RE_SOURCE_LABEL.search(text))
            return passed, {"has_url": bool(_RE_URL.search(text))}
        if mode == "lead_with_conclusion":
            first_block = stripped.split("\n\n", 1)[0].strip()
            passed = bool(_RE_CONCLUSION.search(first_block)) or len(first_block) <= 100
            return passed, {"first_block": first_block[:160]}
        if mode == "max_paragraphs":
            paras = [x.strip() for x in re.split(r"\n\s*\n", stripped) if x.strip()]
            limit = max(1, int(params.get("max_paragraphs", 3) or 3))
            return len(paras) <= limit, {"paragraph_count": len(paras), "limit": limit}
        if mode == "markdown_table":
            lines = [x for x in text.splitlines() if "|" in x]
            passed = len(lines) >= 2 and any("---" in x for x in lines)
            return passed, {"table_line_count": len(lines)}
        return False, {"error": f"unsupported programmatic mode: {mode}"}

    def _evaluate_llm_binary(
        self,
        *,
        rule: EvalRule,
        response_text: str,
        sample: ReplaySample,
        variant: SkillSnapshot,
    ) -> Tuple[bool, Dict[str, Any]]:
        requirement = str(rule.params.get("requirement_text") or rule.description or "").strip()
        if not requirement:
            return False, {"error": "missing_requirement_text"}
        if self.judge_llm is None:
            return False, {"error": "judge_llm_not_configured"}
        system = (
            "You are a strict binary evaluator for skill replay results.\n"
            "Output ONLY strict JSON parseable by json.loads.\n"
            'Schema: {"pass": true|false, "reason": "short reason"}\n'
            "Judge only against the requirement provided.\n"
            "Prefer false if the requirement is not clearly satisfied.\n"
        )
        user = json.dumps(
            {
                "requirement": requirement,
                "skill_name": variant.name,
                "latest_user_message": sample.latest_user_message(),
                "response": str(response_text or ""),
            },
            ensure_ascii=False,
        )
        try:
            raw = self.judge_llm.complete(system=system, user=user, temperature=0.0)
            obj = json.loads(raw)
            if not isinstance(obj, dict):
                return False, {"error": "judge_output_not_object", "raw": raw[:500]}
            passed = bool(obj.get("pass", False))
            return passed, {"reason": str(obj.get("reason") or "")[:500]}
        except Exception as e:
            return False, {"error": "judge_parse_failed", "detail": str(e)}
