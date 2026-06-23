"""
Standalone prompt builders for offline extraction channels.

Important:
- Offline channels use these prompt bodies directly.
- AutoSkill4Doc only keeps the document channel.
"""

from __future__ import annotations

from typing import Any


OFFLINE_CHANNEL_DOC = "offline_extract_from_doc"

_OFFLINE_CHANNELS = {
    OFFLINE_CHANNEL_DOC,
}


def _taxonomy_guidance_text(taxonomy: Any) -> str:
    """Builds prompt guidance for one selected skill taxonomy."""

    if taxonomy is None:
        return ""
    guidance = getattr(taxonomy, "prompt_guidance", None)
    if callable(guidance):
        text = str(guidance() or "").strip()
        if text:
            return f"\nTaxonomy guidance:\n{text}\n"
    return ""


def is_offline_channel(channel: str) -> bool:
    """Run is offline channel."""
    return str(channel or "").strip().lower() in _OFFLINE_CHANNELS


def build_offline_extract_prompt(*, channel: str, max_candidates: int, taxonomy: Any = None) -> str:
    """Run build offline extract prompt."""
    ch = str(channel or "").strip().lower()

    if ch != OFFLINE_CHANNEL_DOC:
        return ""

    taxonomy_guidance = _taxonomy_guidance_text(taxonomy)
    if int(max_candidates or 0) <= 3:
        planner_volume_hint = (
            f"- Prefer 0-{max_candidates} assets. "
            f"Use {max_candidates} only when the excerpt clearly contains that many distinct reusable assets.\n\n"
        )
    else:
        planner_volume_hint = (
            f"- Prefer 0-3 assets. "
            f"Use 4-{max_candidates} only when the excerpt clearly contains that many distinct reusable assets.\n\n"
        )
    return (
        "You are AutoSkill's offline DOCUMENT skill extractor.\n"
        "Task: FIRST plan how many reusable assets are really present in one document window.\n"
        "Output ONLY strict JSON parseable by json.loads.\n\n"
        "Decision policy:\n"
        "- Be conservative. Missing one weak asset is better than inventing or over-generalizing one.\n"
        "- Treat each asset as a callable reusable contract: when to invoke it, when not to invoke it, what it executes, and what output or handoff it should produce.\n"
        "- Plan only assets that are operational enough for another practitioner or system to reuse.\n"
        "- If the text is mainly case narrative, outcomes, literature review, or publication metadata, return {\"skills\": []}.\n"
        f"{planner_volume_hint}"
        "Rules:\n"
        "1) One document may produce zero, one, or MANY assets; do not force one asset per paper.\n"
        "2) Extract reusable method/policy/workflow/intervention assets only; do not summarize narrative facts.\n"
        "3) Each asset must stay single-goal: one primary objective, one primary stage, and one primary method family.\n"
        "4) Keep macro_protocol, session_skill, micro_skill, safety_rule, and knowledge_reference separate; never merge macro and micro assets into one item.\n"
        "5) micro_skill means one therapist move or one tightly-coupled mini-sequence; do not package toolkits, full sessions, or multi-step stage workflows as micro_skill.\n"
        "6) safety_rule is mandatory for suicide/self-harm/violence/crisis screening, escalation, safety planning, or referral logic.\n"
        "7) session_skill means one session-phase scaffold; macro_protocol means cross-phase or multi-stage treatment flow.\n"
        "8) De-identify: remove names, IDs, dates, local paths, one-off payload details.\n"
        "9) Keep hard constraints, safety rules, required sequence, therapist moves, and output checks.\n"
        "10) Prefer finer reusable assets when evidence is specific enough, especially micro interventions and safety rules.\n"
        "11) Include 1-3 short therapist-response examples when the source supports them.\n"
        "12) If no durable reusable asset exists, return {\"skills\": []}.\n"
        "13) Keep only assets likely to be reused by the same user/team.\n\n"
        f"{taxonomy_guidance}"
        f"Return schema: {{\"skills\": [...]}} with at most {max_candidates} item(s).\n"
        "Each planned skill item fields:\n"
        "- slot (1-based integer)\n"
        "- name\n"
        "- description (1-2 short sentences describing what the asset does and when to use it)\n"
        "- asset_type (macro_protocol|session_skill|micro_skill|safety_rule|knowledge_reference)\n"
        "- optional asset_node_id (must be one configured taxonomy node id when present)\n"
        "- granularity (macro|session|micro), objective\n"
        "- domain, task_family, method_family, stage\n"
        "- optional use_when (1-3 short routing cues or entry conditions)\n"
        "- optional do_not_use_when (0-3 short non-goal, boundary, or unsafe-use cues)\n"
        "- optional success_artifact (one short statement describing the expected output, handoff, or completion artifact)\n"
        "- why_distinct (short reason this is a separate asset)\n"
        "- optional evidence_span_hint (short quoted anchor or heading hint)\n"
        "- confidence (0.0-1.0)\n\n"
        "Field boundaries:\n"
        "- name: short reusable capability name, not a paper title or patient description.\n"
        "- description: concise scope summary for later detailed expansion; do not write a long prompt or evidence recap.\n"
        "- use_when: observable invocation cues such as user intent, client state, or session condition; not generic topical keywords.\n"
        "- do_not_use_when: clear boundaries, exclusions, or safety constraints showing when this skill should NOT be selected.\n"
        "- success_artifact: the concrete output, handoff, or state change that tells a caller the skill completed successfully.\n"
        "- task_family/method_family/stage should use compact reusable labels, not broad domain labels such as 心理咨询 / psychology.\n"
        "- asset_node_id, when present, must be a configured taxonomy node id; otherwise omit it.\n"
        "- why_distinct must explain why this is not just a duplicate or sub-part of another planned asset.\n\n"
        "Language:\n"
        "- Use one dominant language from the source text for ALL textual fields.\n"
        "- If dominant language is unclear, return {\"skills\": []}.\n\n"
        "JSON validity:\n"
        "- Escape newlines as \\n and escape quotes correctly.\n"
        "- No Markdown wrapper, output raw JSON only.\n"
    )


def build_offline_repair_prompt(*, channel: str, max_candidates: int, taxonomy: Any = None) -> str:
    """Run build offline repair prompt."""
    ch = str(channel or "").strip().lower()
    if ch != OFFLINE_CHANNEL_DOC:
        return ""

    label = "document"
    keep_fields = (
        "name, description, prompt, triggers, tags, asset_type, asset_node_id, granularity, objective, "
        "domain, task_family, method_family, stage, applicable_signals, intervention_moves, contraindications, "
        "workflow_steps, constraints, cautions, output_contract, examples, relation_type, risk_class, confidence, "
        "optional resources/files"
    )
    taxonomy_guidance = _taxonomy_guidance_text(taxonomy)

    return (
        f"You are a JSON fixer for offline {label} skill extraction.\n"
        "Given DATA and DRAFT, output ONLY strict JSON: {\"skills\": [...]} with no commentary.\n"
        f"Return at most {max_candidates} skill(s); if uncertain return {{\"skills\": []}}.\n"
        "Be conservative: fix malformed output, but do not infer unsupported skills or fields.\n"
        "Keep only reusable, de-identified rules/workflows likely to be reused by the same user/team.\n"
        "Drop one-off facts, entity names, assistant/platform artifacts, and non-portable payload.\n"
        f"{taxonomy_guidance}"
        f"Keep schema fields: {keep_fields}.\n"
        "Keep asset types and asset_node_id values inside the configured taxonomy only.\n"
        "If resources/files exist, keep only concise reusable assets with safe relative paths.\n"
        "Use one dominant language consistently across all textual fields; if unclear return {\"skills\": []}.\n"
        "Ensure JSON validity (escape newlines as \\n).\n"
    )


def build_offline_extract_plan_repair_prompt(*, channel: str, max_candidates: int, taxonomy: Any = None) -> str:
    """Builds a strict JSON repair prompt for planned skill sketches."""

    ch = str(channel or "").strip().lower()
    if ch != OFFLINE_CHANNEL_DOC:
        return ""

    taxonomy_guidance = _taxonomy_guidance_text(taxonomy)
    return (
        "You are a JSON fixer for offline document skill planning.\n"
        "Given DATA and DRAFT, output ONLY strict JSON: {\"skills\": [...]} with no commentary.\n"
        f"Return at most {max_candidates} planned skill(s); if uncertain return {{\"skills\": []}}.\n"
        "Be conservative: fix malformed JSON, but do not invent unsupported skills or detailed workflow fields.\n"
        "Keep only lightweight planned assets that are reusable, de-identified, and clearly distinct within the current window.\n"
        f"{taxonomy_guidance}"
        "Keep each item limited to: slot, name, description, asset_type, asset_node_id, granularity, objective, "
        "domain, task_family, method_family, stage, use_when, do_not_use_when, success_artifact, why_distinct, evidence_span_hint, confidence.\n"
        "Keep asset types and asset_node_id values inside the configured taxonomy only.\n"
        "Use one dominant language consistently across all textual fields; if unclear return {\"skills\": []}.\n"
        "Ensure JSON validity (escape newlines as \\n).\n"
    )


def build_offline_extract_expand_prompt(*, channel: str, taxonomy: Any = None) -> str:
    """Builds the second-pass prompt that expands one planned asset into a full skill."""

    ch = str(channel or "").strip().lower()
    if ch != OFFLINE_CHANNEL_DOC:
        return ""

    taxonomy_guidance = _taxonomy_guidance_text(taxonomy)
    return (
        "You are AutoSkill's offline DOCUMENT skill extractor.\n"
        "Task: expand ONE planned reusable asset from one document window into one complete executable skill.\n"
        "Output ONLY strict JSON parseable by json.loads.\n\n"
        "Decision policy:\n"
        "- Expand only the provided planned asset; do not add a second asset.\n"
        "- Treat the result as a reusable skill contract with routing cues, guardrails, execution steps, and an output or handoff guarantee.\n"
        "- Be conservative. If the candidate is not sufficiently supported by the excerpt, return {\"skill\": null}.\n"
        "- Keep the asset single-goal and reusable.\n\n"
        "Rules:\n"
        "1) Treat the candidate name, candidate description, candidate use_when, candidate do_not_use_when, and candidate success_artifact as the scope anchor.\n"
        "2) Do not rename the asset into a different capability unless the excerpt clearly requires a minor normalization.\n"
        "3) Do not expand beyond the planned scope or merge in unrelated steps from the same window.\n"
        "4) Keep macro_protocol, session_skill, micro_skill, safety_rule, and knowledge_reference separate.\n"
        "5) Translate candidate use_when into triggers/applicable_signals, candidate do_not_use_when into contraindications/constraints, and candidate success_artifact into output_contract whenever the excerpt supports them.\n"
        "6) Keep hard constraints, safety rules, therapist moves, sequence, and output checks when directly supported.\n"
        "7) Preserve caller-facing boundaries: the skill should make it clear when a caller should invoke it, when a caller should avoid it, and what the caller gets back.\n"
        "8) De-identify: remove names, IDs, dates, local paths, one-off payload details.\n"
        "9) If the excerpt only partially supports the candidate, keep the skill minimal instead of hallucinating details.\n"
        "10) Include 1-3 short therapist-response examples only when the source directly supports them.\n\n"
        f"{taxonomy_guidance}"
        "Return schema: {\"skill\": {...}} or {\"skill\": null}.\n"
        "Skill fields:\n"
        "- name, description, prompt, triggers, tags\n"
        "- asset_type (macro_protocol|session_skill|micro_skill|safety_rule|knowledge_reference)\n"
        "- optional asset_node_id (must be one configured taxonomy node id when present)\n"
        "- granularity (macro|session|micro), objective\n"
        "- domain, task_family, method_family, stage\n"
        "- applicable_signals, intervention_moves, contraindications\n"
        "- workflow_steps, constraints, cautions, output_contract\n"
        "- examples: array of 1-3 short objects like {input, output, notes?}\n"
        "- relation_type (support|constraint|conflict|case_variant), risk_class (low|medium|high)\n"
        "- confidence (0.0-1.0)\n"
        "- optional resources/files (safe relative paths under scripts/, references/, assets/; concise content only)\n\n"
        "Field boundaries:\n"
        "- description: what the asset does and when to use it, not evidence recap.\n"
        "- prompt: only execution guidance for the asset itself; do not repeat article metadata or long quotations.\n"
        "- triggers and applicable_signals: routing cues and entry conditions that tell a caller when to invoke this skill.\n"
        "- contraindications and constraints: when not to use the skill, or what conditions must hold before and during execution.\n"
        "- output_contract: the completion artifact, handoff, or observable success condition for downstream callers.\n"
        "- task_family/method_family/stage should use compact reusable labels, not broad domain labels such as 心理咨询 / psychology.\n"
        "- asset_node_id, when present, must be a configured taxonomy node id; otherwise omit it.\n"
        "- examples should be omitted unless the source directly supports concrete example language.\n\n"
        "Language:\n"
        "- Use one dominant language from the source text for ALL textual fields.\n"
        "- If dominant language is unclear, return {\"skill\": null}.\n\n"
        "JSON validity:\n"
        "- Escape newlines as \\n and escape quotes correctly.\n"
        "- No Markdown wrapper, output raw JSON only.\n"
    )


def build_offline_extract_expand_repair_prompt(*, channel: str, taxonomy: Any = None) -> str:
    """Builds a strict JSON repair prompt for one expanded skill."""

    ch = str(channel or "").strip().lower()
    if ch != OFFLINE_CHANNEL_DOC:
        return ""

    taxonomy_guidance = _taxonomy_guidance_text(taxonomy)
    return (
        "You are a JSON fixer for offline document skill extraction.\n"
        "Given DATA and DRAFT, output ONLY strict JSON: {\"skill\": {...}} or {\"skill\": null} with no commentary.\n"
        "Be conservative: fix malformed JSON, but do not invent unsupported fields or add a second asset.\n"
        "Keep only reusable, de-identified execution guidance supported by the excerpt.\n"
        f"{taxonomy_guidance}"
        "Keep asset types and asset_node_id values inside the configured taxonomy only.\n"
        "Use one dominant language consistently across all textual fields; if unclear return {\"skill\": null}.\n"
        "Ensure JSON validity (escape newlines as \\n).\n"
    )


def build_offline_manage_decide_prompt(channel: str) -> str:
    """Run build offline manage decide prompt."""
    ch = str(channel or "").strip().lower()
    if ch not in {"doc", OFFLINE_CHANNEL_DOC}:
        return ""
    focus = (
        "Channel focus: documents. Prefer MERGE when methodology/workflow is the same and candidate is an incremental improvement; "
        "ADD only for clearly distinct method family or objective."
    )

    return (
        "You are AutoSkill's Offline Skill Set Manager.\n"
        "Task: decide add / merge / discard for candidate_skill against similar existing skills.\n"
        "Output ONLY strict JSON; no Markdown, no extra text.\n\n"
        f"{focus}\n"
        "Global rules:\n"
        "- Prevent fragmentation: same capability should not be added as a new skill.\n"
        "- Name/wording changes alone are not new capabilities.\n"
        "- Use similarity as hint only; rely on invocation boundary + objective + deliverable + constraints + success criteria.\n"
        "- If overlap is high but value is low, choose discard.\n"
        "- Prefer quality over recall; when uncertain between add and merge, prefer discard or merge.\n"
        "- target_skill_id, when action=merge, must be chosen only from the provided existing skills.\n"
        "- If no valid existing target exists, choose add or discard instead of inventing one.\n\n"
        "Return schema:\n"
        "{\n"
        "  \"action\": \"add\"|\"merge\"|\"discard\",\n"
        "  \"target_skill_id\": \"string\"|null,\n"
        "  \"reason\": \"short reason\"\n"
        "}\n"
    )


def build_offline_merge_gate_prompt(channel: str) -> str:
    """Run build offline merge gate prompt."""
    ch = str(channel or "").strip().lower()
    if ch not in {"doc", OFFLINE_CHANNEL_DOC}:
        return ""
    focus = "Judge capability identity by method/framework + deliverable objective, not wording."

    return (
        "You are AutoSkill's Offline Capability Identity Judge.\n"
        "Task: decide whether candidate_skill and existing_skill are the SAME capability.\n"
        "Output ONLY strict JSON parseable by json.loads.\n\n"
        f"{focus}\n"
        "Rules:\n"
        "- Ignore surface wording differences.\n"
        "- Incremental refinements/robustness updates are usually same capability.\n"
        "- If invocation boundary, objective, deliverable class, audience, guardrails, or evaluation criteria changes materially, they are different capabilities.\n"
        "- Do not rely on name overlap alone; require compatible invocation cues + workflow + constraints + output contract.\n"
        "- If uncertain, default to same_capability=false.\n\n"
        "Return schema:\n"
        "{\n"
        "  \"same_capability\": true|false,\n"
        "  \"confidence\": 0.0-1.0,\n"
        "  \"reason\": \"short reason\"\n"
        "}\n"
    )


def build_offline_merge_prompt(channel: str) -> str:
    """Run build offline merge prompt."""
    ch = str(channel or "").strip().lower()
    if ch not in {"doc", OFFLINE_CHANNEL_DOC}:
        return ""
    fusion = "Merge methodology/rules/checklists into one coherent protocol; keep unique safety constraints."

    return (
        "You are AutoSkill's Offline Skill Merger.\n"
        "Task: merge existing_skill and candidate_skill into ONE improved skill.\n"
        "Output ONLY strict JSON parseable by json.loads.\n\n"
        f"{fusion}\n"
        "Rules:\n"
        "- Keep the same capability identity; do not expand to unrelated tasks.\n"
        "- Perform semantic union, not raw concatenation.\n"
        "- Deduplicate triggers/tags and repeated prompt sections.\n"
        "- Keep reusable routing cues, constraints, and output guarantees; drop one-off payload details.\n"
        "- Preserve the stronger safety constraints and clearer workflow ordering when the two conflict.\n"
        "- If candidate adds no durable value, keep existing mostly unchanged.\n\n"
        "Return schema fields only: {name, description, prompt, triggers, tags}.\n"
        "JSON validity: escape newlines as \\n; output raw JSON only.\n"
    )


def maybe_offline_prompt(
    *,
    channel: str,
    kind: str,
    max_candidates: Optional[int] = None,
    taxonomy: Any = None,
) -> str:
    """Run maybe offline prompt."""
    ch = str(channel or "").strip().lower()
    k = str(kind or "").strip().lower()
    if not is_offline_channel(ch):
        return ""
    if k == "extract":
        return build_offline_extract_prompt(channel=ch, max_candidates=int(max_candidates or 1), taxonomy=taxonomy)
    if k == "extract_plan":
        return build_offline_extract_prompt(channel=ch, max_candidates=int(max_candidates or 1), taxonomy=taxonomy)
    if k == "extract_plan_repair":
        return build_offline_extract_plan_repair_prompt(channel=ch, max_candidates=int(max_candidates or 1), taxonomy=taxonomy)
    if k == "extract_expand":
        return build_offline_extract_expand_prompt(channel=ch, taxonomy=taxonomy)
    if k == "extract_expand_repair":
        return build_offline_extract_expand_repair_prompt(channel=ch, taxonomy=taxonomy)
    if k == "repair":
        return build_offline_repair_prompt(channel=ch, max_candidates=int(max_candidates or 1), taxonomy=taxonomy)
    if k == "manage_decide":
        return build_offline_manage_decide_prompt(ch)
    if k == "merge_gate":
        return build_offline_merge_gate_prompt(ch)
    if k == "merge":
        return build_offline_merge_prompt(ch)
    return ""
