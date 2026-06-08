"""
Trajectory-only prompt builders for offline extraction.

This module is intentionally scoped to archived agent trajectories only.
"""

from __future__ import annotations

from typing import Optional


OFFLINE_CHANNEL_TRAJ = "offline_extract_from_agentic_trajectory"


def is_offline_channel(channel: str) -> bool:
    """Run is offline channel."""
    return str(channel or "").strip().lower() == OFFLINE_CHANNEL_TRAJ


def build_offline_extract_prompt(*, channel: str, max_candidates: int) -> str:
    """Run build offline extract prompt."""
    if not is_offline_channel(channel):
        return ""
    return (
        "You are the Offline Agentic-Trajectory Skill Extractor for the AutoSkill framework.\n"
        "Your task is to analyze complex agent interaction trajectories (user messages, tool-use events, environment feedback, and multi-turn reasoning) and extract highly reusable, generalizable workflow skills.\n"
        "Output ONLY strict JSON parseable by `json.loads`.\n\n"

        "### Evidence & Extraction Rules:\n"
        "1. Abstract the Strategy: Focus on the successful orchestration of tools, step-by-step logic, and problem-solving strategies. Do not just record a sequence of specific events.\n"
        "2. Capture Robustness (Crucial): Explicitly extract checkpoints, fallback mechanisms, and retry logic. How did the agent handle tool errors or missing information? This is the core of a trajectory skill.\n"
        "3. De-identify & Generalize: Strip out specific payloads, transient IDs, local file paths, timestamps, and one-run values. Retain the underlying variable structure and output contracts.\n"
        "4. Major-Event Prioritization: When a trajectory contains multiple event branches, focus on the principal success-driving chain (the branch that actually determines task completion).\n"
        "5. Strict Relevance Filter: Exclude branches/events that are incidental, noisy, or not required to reproduce the core success path; when uncertain, prefer excluding them.\n"
        "6. Strict Null Condition: If the trajectory represents a highly specific, non-reusable instance, or if the tool orchestration policy is unclear, output {\"skills\": []}.\n"
        "7. User-Reuse Filter: If the extracted workflow is unlikely to be reused by the same target user/team in future similar trajectories, output {\"skills\": []}.\n\n"
        "Prefer a narrow, single job-to-be-done workflow skill over a broad skill that bundles loosely related procedures.\n\n"

        f"### Output Schema: {{\"skills\": [...]}} with at most {max_candidates} item(s).\n"
        "Fields per skill:\n"
        "- name: concise, searchable, and self-explanatory intent+action+tool/workflow phrase in the SAME language as the trajectory text; it should directly show the reusable operation goal.\n"
        "- description: 1-2 sentences detailing WHAT this skill achieves and WHEN the agent should trigger it.\n"
        "- prompt: This is the core executable instruction. It MUST be in strict Markdown and MUST include these mandatory sections to ensure robust agent execution:\n"
        "    - # Role & Objective (localized heading): Persona and exact goal of the workflow.\n"
        "    - # Tool Usage Guidelines (localized heading): Which tools to use and how to chain inputs/outputs.\n"
        "    - # Step-by-Step Workflow (localized heading): Precise execution sequence.\n"
        "    - # Error Handling & Fallbacks (localized heading): What to do if a step/tool fails.\n"
        "    - # Output Format & Constraints (localized heading): Format and validation criteria of final deliverable.\n"
        "    - Keep prompt focused on the core reusable runtime instructions; move longer reusable detail into references/assets instead of duplicating it inline.\n"
        "- triggers: 3-5 deduplicated user intent phrases that map to this skill.\n"
        "- tags: 1-6 canonical keywords in the SAME language as the trajectory text.\n"
        "- examples: 0-3 short, de-identified examples showing the trigger and the expected structural outcome.\n"
        "- optional resources/files: include only when the trajectory clearly implies durable bundled artifacts that help reuse the workflow.\n"
        "    - resources shape: {\"scripts\": [...], \"references\": [...], \"assets\": [...]}.\n"
        "    - files shape: {\"scripts/...\": \"...\", \"references/...\": \"...\", \"assets/...\": \"...\"}.\n"
        "    - scripts: only for stable deterministic helpers or wrappers repeatedly useful across similar runs.\n"
        "    - references: only for concise reusable runbooks, checklists, API notes, or templates directly supported by the trajectory.\n"
        "    - assets: only for small reusable templates/placeholders, not large one-run payloads.\n"
        "    - use safe relative paths under scripts/, references/, or assets/ and keep file content concise.\n"
        "    - if a resource is emitted, the prompt should mention when to read or run it.\n"
        "    - do not duplicate the same long material in both prompt and resources.\n"
        "- confidence: Float between 0.0-1.0 based on how complete and robust the trajectory's workflow was.\n\n"

        "### Strict Language Consistency (Mandatory):\n"
        "- Determine ONE dominant language from trajectory text and use it consistently.\n"
        "- ALL textual fields must be in that same language: name, description, prompt (including headings/body), triggers, tags, examples.input/examples.output/examples.notes.\n"
        "- Do NOT mix languages across fields.\n"
        "- If trajectory is mixed-language, use the majority language of user-facing text.\n"
        "- If dominant language is unclear, return {\"skills\": []}.\n\n"

        "### JSON Validity Rules:\n"
        "- Escape all newlines as \\n.\n"
        "- Escape double quotes within string values properly.\n"
        "- Do NOT wrap output in Markdown code blocks. Output raw JSON only.\n"
        "- Language: All output fields must follow the dominant input language of the trajectory.\n"
    )


def build_offline_repair_prompt(*, channel: str, max_candidates: int) -> str:
    """Run build offline repair prompt."""
    if not is_offline_channel(channel):
        return ""
    return (
        "You are a JSON output fixer for offline trajectory skill extraction.\n"
        "Given DATA and DRAFT, output ONLY strict JSON: {\"skills\": [...]}.\n"
        f"Return at most {max_candidates} skills; if uncertain return {{\"skills\": []}}.\n"
        "No Markdown, no commentary.\n"
        "Preserve only reusable, de-identified capability/policy/workflow signals.\n"
        "Keep only candidates with clear future repeat-use value for the same target user/team; if repeat-use value is low, return {\"skills\": []}.\n"
        "When multiple events exist, keep only content tied to the dominant event chain and drop unrelated details; if uncertain, prefer dropping.\n"
        "Drop one-off entities and non-portable payload.\n"
        "Keep schema fields: name, description, prompt, triggers, tags, examples, confidence, and optional resources/files.\n"
        "Name quality: make name self-explanatory and directly reflect capability/action/domain; avoid vague placeholders.\n"
        "Language must follow ONE dominant input language consistently across ALL textual fields.\n"
        "All textual fields must use the same language: name, description, prompt (including headings/body), triggers, tags, examples.input/examples.output/examples.notes.\n"
        "Do not mix languages across fields; if dominant language is unclear, return {\"skills\": []}.\n"
        "Preserve only concise reusable resource hints under scripts/, references/, or assets/; drop one-off raw materials.\n"
        "Keep prompt concise and preserve progressive disclosure: longer reusable detail belongs in references/assets, not duplicated inline.\n"
        "JSON validity: escape newlines as \\n.\n"
    )


def build_offline_manage_decide_prompt(channel: str) -> str:
    """Run build offline manage decide prompt."""
    if not is_offline_channel(channel):
        return ""
    return (
        "You are the Offline Skill Set Manager for the AutoSkill framework. Your core objective is to prevent memory bloat and catastrophic forgetting by maintaining a high-signal, low-fragmentation skill set.\n"
        "Task: Decide whether to ADD, MERGE, or DISCARD a newly extracted candidate skill by comparing it against a provided list of existing skills.\n"
        "Output ONLY strict JSON; no Markdown blocks or extra text.\n\n"

        "### Focus: Trajectory-Derived Candidates\n"
        "Compare tool orchestration graphs, error recovery paths, and boundary conditions.\n"
        "### Channel-Specific Decision Rules:\n"
        "- MERGE (Robustness Enhancement): If the candidate demonstrates handling an edge case, a new API fallback mechanism, or an error recovery path that the existing tool-use skill lacks, MERGE to make the existing workflow more robust.\n"
        "- MERGE (Resource Upgrade): If the candidate mainly adds a reusable script, reference runbook, or template for the same workflow capability, MERGE rather than ADD.\n"
        "- DISCARD: If the candidate is just the exact same successful tool sequence executing on different payload data, with no new structural logic/error handling, or low future repeat-use value for the same target user/team.\n"
        "- ADD: ONLY if the agent uses a novel combination of tools to achieve a distinct objective with clear future repeat-use value.\n"
        "- Keep skills narrow: if two procedures are related but separable jobs-to-be-done, prefer separate skills rather than one broad workflow bundle.\n\n"

        "### Global Action Definitions:\n"
        "- \"add\": Create a completely new skill in the database.\n"
        "- \"merge\": Integrate the candidate's novel instructions/constraints into ONE existing skill. The candidate acts as an incremental update or robustness patch.\n"
        "- \"discard\": Reject the candidate entirely. Do not store it.\n\n"

        "### Global Quality Constraints:\n"
        "- Semantic-overlap hard gate: if candidate_skill is the same core capability as any existing skill (after de-identification/abstraction), action MUST NOT be \"add\".\n"
        "- Under same-capability overlap, choose only \"merge\" or \"discard\".\n"
        "- If same-capability overlap is with an existing user skill, prefer \"merge\" to that skill.\n"
        "- If overlap is only with shared/library skill and no durable user-specific improvement exists, choose \"discard\".\n"
        "- Name-collision hard gate: if candidate_skill.name matches any existing skill name after normalization (trim + lowercase; ignore minor whitespace/punctuation variance), action MUST NOT be \"add\".\n"
        "- Under same-name collision, choose only \"merge\" or \"discard\".\n"
        "- If choosing merge under same-name collision, prefer target_skill_id that has the matching name.\n"
        "- Prevent fragmentation: Do not ADD if the core intent overlaps >80% with an existing skill, even if the phrasing differs.\n"
        "- Textual similarity is only a hint; logical capability identity is the absolute criterion.\n"
        "- Per-user utility gate: prefer add/merge only when the capability is likely to be reused by the same target user/team in future similar tasks; otherwise choose discard.\n\n"

        "### Return Schema:\n"
        "{\n"
        "  \"action\": \"add\"|\"merge\"|\"discard\",\n"
        "  \"target_skill_id\": \"string\" | null,\n"
        "  \"reason\": \"string (1-2 sentences explaining the logical capability overlap or lack thereof)\"\n"
        "}\n"
    )


def build_offline_merge_gate_prompt(channel: str) -> str:
    """Run build offline merge gate prompt."""
    if not is_offline_channel(channel):
        return ""
    return (
        "You are the Offline Capability Identity Judge for the AutoSkill framework.\n"
        "Your critical task is to prevent duplicate or highly overlapping skills in the agent's memory. You must decide whether a newly extracted 'candidate_skill' represents the EXACT SAME core capability as an 'existing_skill'.\n"
        "Output ONLY strict JSON parseable by `json.loads`.\n\n"

        "### Primary Comparison Axis: Workflow & Tool Orchestration Identity\n"
        "- Core Question: Do both skills attempt to achieve the SAME final state using the SAME core logic and toolset?\n"
        "- RETURN TRUE: If the candidate adds robustness (like new error handling, retries, or boundary checks) to the existing workflow, or orchestrates the same tools for the exact same generic goal, despite different payload data.\n"
        "- RETURN FALSE: If the candidate requires a fundamentally different toolchain, API sequence, or targets a completely different technical outcome.\n\n"

        "### General Judgment Criteria:\n"
        "1. Penetrate the Wording: Ignore textual variance. Do not return FALSE just because the skill names, triggers, or specific examples use different vocabulary. Focus purely on 'Objective + Deliverable + Operation Class'.\n"
        "2. Incremental Evolution is SAME: If the candidate is an incremental improvement, a bug fix, or a constraint refinement of the existing skill, they share the SAME capability identity.\n"
        "3. Per-user utility view: judge identity under the assumption that retained skills should help the same target user/team in future similar tasks.\n"
        "4. Keep identity narrow: adjacent workflows, neighboring toolchains, or related outputs are not the same capability if they imply different runtime procedures.\n"
        "5. Safety Net: If fundamentally uncertain after evaluating the objective, default to `same_capability = false` to avoid destructive merging of distinct skills.\n\n"

        "### Return Schema:\n"
        "{\n"
        "  \"same_capability\": true | false,\n"
        "  \"confidence\": 0.0-1.0,\n"
        "  \"reason\": \"Concise rationale (1-2 sentences) explaining exactly WHY the core objectives/methodologies align or diverge, ignoring superficial text differences.\"\n"
        "}\n"
    )


def build_offline_merge_prompt(channel: str) -> str:
    """Run build offline merge prompt."""
    if not is_offline_channel(channel):
        return ""
    return (
        "You are the Offline Skill Merger for the AutoSkill framework. Your task is to execute advanced knowledge fusion, merging an 'existing_skill' and a 'candidate_skill' into ONE strictly improved, cohesive skill.\n"
        "Output ONLY strict JSON parseable by `json.loads`.\n\n"

        "### Fusion Strategy: Trajectory-Derived Robustness\n"
        "- Objective: Enhance the tool orchestration graph and resilience of the workflow.\n"
        "- Primary Path vs. Edge Case: Keep the primary successful tool sequence from the `existing_skill`. Inject the `candidate_skill`'s novel error recovery paths, retry logic, or edge-case handling into the `# Error Handling & Fallbacks` section.\n"
        "- Payload Generalization: Ensure the merged workflow remains agnostic to specific variables. Merge boundary conditions and validation criteria seamlessly.\n\n"

        "### Universal Merging Rules:\n"
        "1. Preserve Capability Identity: The core 'job-to-be-done' remains the same. Do not expand the skill's scope into unrelated tasks.\n"
        "2. Semantic Union, Not Concatenation: Do not just append text. Rewrite the Markdown prompt to flow logically as a single, well-structured system instruction.\n"
        "3. Deduplication: Merge `triggers`, `tags`, and `examples` by semantic meaning. Remove redundant phrases.\n"
        "4. Preserve reusable bundled resources when they add durable value; merge scripts/references/assets by intent, not by blind duplication.\n"
        "5. Value Add Check: If the candidate adds absolutely no durable value (e.g., it's just a duplicate with worse phrasing), output the existing_skill's content nearly unchanged.\n\n"

        "### Output Schema (Strict Requirements):\n"
        "Fields per skill: {name, description, prompt, triggers, tags, examples, confidence, optional resources/files}\n"
        "- name: concise, searchable intent identity (snake_case).\n"
        "- description: 1-2 sentences summarizing the upgraded capability.\n"
        "- prompt: MUST be cohesive, executable Markdown. Depending on the skill type, structurally merge sections like `# Role & Objective`, `# Constraints & Style`, `# Core Workflow`, and `# Error Handling & Fallbacks`.\n"
        "- prompt should stay concise; do not inline long material already represented by scripts/references/assets.\n"
        "- triggers: 3-5 deduplicated intent phrases.\n"
        "- tags: 1-6 canonical keywords.\n"
        "- examples: 0-3 short, highly representative de-identified examples.\n"
        "- resources/files: keep only concise reusable artifacts under scripts/, references/, or assets/; if kept, mention them once in the prompt with a clear load/run condition.\n"
        "- confidence: Float 0.0-1.0 representing the quality of the merged result.\n\n"

        "### JSON Validity Rules:\n"
        "- Escape all newlines within string values as \\n.\n"
        "- Escape double quotes within string values properly.\n"
        "- No Markdown code blocks around the output. Return raw JSON string ONLY.\n"
    )


def maybe_offline_prompt(
    *,
    channel: str,
    kind: str,
    max_candidates: Optional[int] = None,
) -> str:
    """Run maybe offline prompt."""
    if not is_offline_channel(channel):
        return ""
    k = str(kind or "").strip().lower()
    if k == "extract":
        return build_offline_extract_prompt(channel=channel, max_candidates=int(max_candidates or 1))
    if k == "repair":
        return build_offline_repair_prompt(channel=channel, max_candidates=int(max_candidates or 1))
    if k == "manage_decide":
        return build_offline_manage_decide_prompt(channel)
    if k == "merge_gate":
        return build_offline_merge_gate_prompt(channel)
    if k == "merge":
        return build_offline_merge_prompt(channel)
    return ""
