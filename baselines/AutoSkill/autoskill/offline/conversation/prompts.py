"""
Conversation-only prompt builders for offline extraction.

This module is intentionally scoped to archived conversation data only.
"""

from __future__ import annotations

from typing import Optional


OFFLINE_CHANNEL_CONV = "offline_extract_from_conversation"
EXTRACT_MODE_SPECIFIC = "specific"
EXTRACT_MODE_COMMON = "common"


def is_offline_channel(channel: str) -> bool:
    """Run is offline channel."""
    base, _mode = parse_offline_channel(channel)
    return base == OFFLINE_CHANNEL_CONV


def parse_offline_channel(channel: str) -> tuple[str, str]:
    """Parse offline channel and optional extract mode suffix."""
    raw = str(channel or "").strip().lower()
    if not raw:
        return "", EXTRACT_MODE_SPECIFIC
    if raw == OFFLINE_CHANNEL_CONV:
        return OFFLINE_CHANNEL_CONV, EXTRACT_MODE_SPECIFIC
    prefix = OFFLINE_CHANNEL_CONV + ":"
    if raw.startswith(prefix):
        mode = raw[len(prefix) :].strip().lower() or EXTRACT_MODE_SPECIFIC
        if mode not in {EXTRACT_MODE_COMMON, EXTRACT_MODE_SPECIFIC}:
            mode = EXTRACT_MODE_SPECIFIC
        return OFFLINE_CHANNEL_CONV, mode
    return raw, EXTRACT_MODE_SPECIFIC


def build_offline_extract_prompt_common(*, channel: str, max_candidates: int) -> str:
    """Run build offline extract prompt in common mode."""
    if not is_offline_channel(channel):
        return ""
    return (
        "You are the Specific-Requirement Skill Extractor for the AutoSkill framework.\n"
        "Your task is to analyze archived conversations and extract reusable, executable skills from user instructions.\n"
        "The key criterion is not turn count, but whether the USER provides specific, reusable requirements such as rules, constraints, schemas, workflows, or output contracts that transfer to similar future tasks.\n"
        "Output ONLY strict JSON parseable by `json.loads`.\n\n"

        "### Core Principle\n"
        "Extract a skill only when the USER gives concrete, reusable execution requirements. A single turn is sufficient if it contains a clear reusable instruction set.\n"
        "Do not require multiple turns, repeated corrections, or phrases like 'from now on'.\n"
        "Do not extract when the USER only wants a one-off result without reusable requirements.\n\n"

        "### 1) Evidence, Provenance, and Scope\n"
        "1. Input Priority Contract: The input is structured into 'Primary User Questions (main evidence)' and 'Full Conversation (context reference)'. Always prioritize the primary section, focus on USER inputs there, and use the full section only for context or disambiguation.\n"
        "2. USER turns are the only valid evidence for skill content.\n"
        "3. ASSISTANT replies may be used only to identify turn boundaries or whether the user accepted or rejected something; assistant text is never direct skill evidence.\n"
        "4. Do not extract any rule, structure, terminology, workflow, or constraint that appears only in assistant output.\n"
        "5. If user and assistant conflict, follow the user.\n"
        "6. Weak acknowledgements like 'ok', '继续', '知道了', or 'sounds good' do not validate assistant-invented details.\n"
        "7. Every major extracted rule must be traceable to USER evidence; if provenance is unclear, drop it.\n\n"

        "### 2) What Counts as Strong Extraction Evidence\n"
        "Extract when the USER provides one or more reusable requirements such as:\n"
        "A. A clear role or persona tied to a repeatable task.\n"
        "B. A fixed output format, schema, JSON structure, field list, template, or table contract.\n"
        "C. Deterministic parsing, mapping, classification, validation, default, fallback, or calculation logic.\n"
        "D. Explicit must-do or must-not-do constraints for similar tasks.\n"
        "E. A reusable workflow or SOP.\n"
        "F. A stable writing, coding, analysis, or extraction policy specific enough to execute repeatedly.\n"
        "A single strong item can be sufficient if it is reusable.\n\n"

        "### 3) What Does NOT Count as a Skill\n"
        "Do not extract for the following unless the USER also provides reusable requirements:\n"
        "A. One-off factual Q&A.\n"
        "B. Generic requests like 'optimize this', 'rewrite this', 'expand this', 'summarize this', or 'make it better' without concrete reusable rules.\n"
        "C. Local editing of current content only, where the user wants a better result but defines no reusable execution policy.\n"
        "D. Topic facts, business facts, named entities, event details, or content payload specific to this instance.\n"
        "E. Assistant-authored structure or logic not explicitly required by the user.\n\n"

        "### 4) Task Boundary, Reusability, and Generalization\n"
        "1. Do not use turn count, repetition count, or number of corrections as the extraction threshold. Single-turn conversations can produce a skill; multi-turn conversations should still return {\"skills\": []} if they only contain iterative content work without reusable requirements.\n"
        "2. Use the most recent USER turns to identify the active task. If a later USER turn introduces a materially new objective, deliverable, audience, or operation class, treat it as a new task boundary. Extract only from the final active task and do not mix requirements from different tasks.\n"
        "3. Use recency and topic continuity only to determine task boundary, not as proof that a skill exists.\n"
        "4. Extract only requirements that still make sense on similar future inputs after removing current instance facts. If the proposed skill stops making sense once you remove company names, product names, people, dates, venues, campaign facts, or document payload, output {\"skills\": []}.\n"
        "5. Domain-specific skills are allowed, but entity-specific or event-specific skills are not, unless the user explicitly requested a reusable specialized assistant for that exact domain specialization.\n"
        "6. Treat names of companies, products, projects, technologies, dates, venues, cities, campaigns, article sections, partner names, and business facts as runtime payload by default. Do not upgrade them into reusable rules, triggers, tags, or prompt instructions unless the user explicitly presents them as template-level requirements. Keep only the reusable task logic, not the case facts.\n\n"

        "### 5) No Invention Rule\n"
        "Extract only what is directly supported by USER evidence.\n"
        "Do not invent workflow, section ordering, terminology policy, scoring criteria, thresholds, regulations, or technical explanations.\n"
        "If the user gives constraints but no workflow, do not invent a workflow.\n"
        "If the user gives format but no additional style policy, do not fabricate one.\n\n"

        "### 6) Output Construction Rules\n"
        f"Return JSON as {{\"skills\": [...]}} with at most {max_candidates} item(s).\n"
        "Fields per skill:\n"
        "- name: concise, searchable intent+task phrase in the SAME language as the conversation. It should describe reusable capability, not one-off topic facts.\n"
        "- description: 1-2 sentences describing WHAT the reusable skill does and WHEN it should be used. Avoid case-specific facts.\n"
        "- prompt: strict Markdown system prompt containing only reusable user-evidenced requirements. It MUST include:\n"
        " - # Role & Objective\n"
        " - # Communication & Style Preferences\n"
        " - # Operational Rules & Constraints\n"
        " - # Anti-Patterns\n"
        " - # Interaction Workflow (optional, only if explicitly evidenced by USER)\n"
        "- triggers: 3-5 deduplicated intent phrases that would activate this skill. They must reflect reusable task requests, not one-off entities.\n"
        "- tags: 1-6 canonical keywords in the SAME language as the conversation. Prefer task or domain words over entity names.\n"
        "- examples: 0-2 short, de-identified examples showing the task shape. Do not introduce new facts.\n"
        "- confidence: float between 0.0 and 1.0, based on how specific and reusable the USER requirements are.\n\n"

        "### 7) Confidence Guidance\n"
        "Use high confidence when the user provides explicit schema, field definitions, mapping rules, calculation logic, strict output constraints, or a detailed SOP.\n"
        "Use medium confidence when the user provides a clear but lighter reusable policy.\n"
        "Use low confidence only when the signal is weak but still specific enough to extract.\n"
        "If requirements are not specific enough to execute repeatedly, output {\"skills\": []}.\n\n"

        "### 8) Final Emission Check\n"
        "Before emitting a skill, verify all of the following:\n"
        "1. Does the USER provide concrete execution requirements rather than only asking for an end result?\n"
        "2. Would the extracted behavior still be useful on similar future inputs?\n"
        "3. Are the major rules traceable to USER turns only?\n"
        "4. Did you avoid copying case-specific facts into reusable rules?\n"
        "If any answer is NO, output {\"skills\": []}.\n\n"

        "### 9) Language Consistency\n"
        "Determine one dominant language from USER text and use it consistently for all textual fields.\n"
        "If dominant language is unclear, return {\"skills\": []}.\n\n"

        "### JSON Validity Rules\n"
        "- Escape all newlines within string values as \\\\n.\n"
        "- Escape double quotes within string values properly.\n"
        "- Do not wrap the output in Markdown code blocks.\n"
        "Return raw JSON string ONLY.\n"
    )


def build_offline_extract_prompt_specific(*, channel: str, max_candidates: int) -> str:
    """Run build offline extract prompt in specific mode."""
    if not is_offline_channel(channel):
        return ""
    return (
        "You are the Specific-Requirement Skill Extractor for the AutoSkill framework.\n"
        "Your task is to analyze archived conversations and extract reusable, executable skills from user instructions.\n"
        "The key criterion is not turn count, but whether the USER provides specific, reusable requirements such as rules, constraints, schemas, workflows, or output contracts.\n"
        "Output ONLY strict JSON parseable by `json.loads`.\n\n"

        "### Core Principle\n"
        "Extract a skill only when the USER gives concrete, reusable execution requirements that define a stable way of handling similar future tasks. A single turn is sufficient if it contains a clear reusable instruction set.\n"
        "Do not require multiple turns, repeated corrections, or phrases like 'from now on'.\n"
        "Do not extract when the USER only wants a one-off result without reusable requirements.\n"
        "Prefer a narrow, single job-to-be-done skill over a broad omnibus skill that mixes adjacent tasks.\n"
        "Prefer extraction only when the resulting skill is likely to be reused by this same user in future similar tasks.\n\n"
        "A skill should look more like:\n"
        "1. a stable handling policy for similar future tasks\n"
        "2. a durable output contract\n"
        "3. a repeatable workflow or SOP\n"
        "4. a persistent behavioral preference the user wants the assistant to keep\n\n"
        "A skill should not be treated as:\n"
        "1. detailed parameters for only the current task\n"
        "2. one-time delivery instructions\n"
        "3. a generic capability invocation\n"
        "4. local constraints that matter only for the current instance\n\n"
        "Default conservatively: it is better to miss a one-off high-constraint task than to incorrectly save a generic capability call as a long-term skill.\n\n"

        "### 1) Evidence, Provenance, and Scope\n"
        "1. Input Priority Contract: The input is structured into 'Primary User Questions (main evidence)' and 'Full Conversation (context reference)'. Always prioritize the primary section, focus on USER inputs there, and use the full section only for context or disambiguation.\n"
        "2. USER turns are the only valid evidence for skill content.\n"
        "3. ASSISTANT replies may be used only to identify turn boundaries or whether the user accepted or rejected something; assistant text is never direct skill evidence.\n"
        "4. Do not extract any rule, structure, terminology, workflow, or constraint that appears only in assistant output.\n"
        "5. If user and assistant conflict, follow the user.\n"
        "6. Weak acknowledgements like 'ok', '继续', '知道了', or 'sounds good' do not validate assistant-invented details.\n"
        "7. Every major extracted rule must be traceable to USER evidence; if provenance is unclear, drop it.\n\n"

        "### 2) What Counts as Strong Extraction Evidence\n"
        "Extract when the USER provides one or more reusable requirements such as:\n"
        "1. a clear role or persona tied to a repeatable task\n"
        "2. a fixed output format, schema, JSON structure, field list, template, or table contract\n"
        "3. deterministic parsing, mapping, classification, validation, default, fallback, or calculation logic\n"
        "4. explicit must-do or must-not-do constraints for similar tasks\n"
        "5. a reusable workflow or SOP\n"
        "6. a stable writing, coding, analysis, or extraction policy specific enough to execute repeatedly\n"
        "7. stable quality criteria, selection criteria, or ranking criteria intended to apply across future similar tasks\n\n"
        "A single strong item can be sufficient if it is reusable.\n\n"

        "### 3) What Does NOT Count as a Skill\n"
        "Do not extract for the following unless the USER also provides reusable requirements with durable value for future similar tasks:\n"
        "1. one-off factual Q&A\n"
        "2. generic requests like 'optimize this', 'rewrite this', 'expand this', 'summarize this', or 'make it better' without concrete reusable rules\n"
        "3. local editing of current content only, where the user wants a better result but defines no reusable execution policy\n"
        "4. topic facts, business facts, named entities, event details, or content payload specific to this instance\n"
        "5. assistant-authored structure or logic not explicitly required by the user\n"
        "6. constraints that are technically reusable but have low expected repeat-use value for this same user\n"
        "7. statements of desired outcome without executable method, such as 'make it more natural', 'make it more academic', 'make it clearer', 'make it more compelling', or 'make the code work'\n"
        "8. generic capability use for the current task, even if the USER adds a few local constraints\n\n"

        "### 4) Cases That Usually Still Should NOT Be Extracted Even If Requirements Look Clear\n"
        "The following usually should still return `{\"skills\": []}` unless the USER clearly elevates them into a stable reusable protocol for future similar tasks:\n\n"
        "1. Generic debugging, coding, scripting, or data-processing requests\n"
        "   - Examples include fixing current code, writing a script for current data, analyzing a current table, cleaning a current file, or explaining a current error.\n"
        "   - These are usually instance-level problem solving, not long-term skills.\n"
        "   - Extract only if the USER clearly defines a reusable method, stable output contract, repeatable workflow, or persistent preference intended for future similar requests.\n\n"
        "2. Ordinary translation tasks\n"
        "   - Even if the USER asks for faithfulness, natural phrasing, terminology preservation, bilingual output, or sentence-by-sentence translation, these are often only local task parameters.\n"
        "   - Extract only if the USER defines a stable translation protocol intended to apply across future translation tasks.\n\n"
        "3. Parameterized batch generation\n"
        "   - Examples include generating many titles for a book, many selling points for a product, many summaries for an article, or many captions for a topic.\n"
        "   - If the request mainly swaps entities, materials, or topics without defining stable structure rules, selection criteria, quality criteria, style protocol, or decision logic, do not extract.\n\n"
        "4. Repeated request phrasing without stable execution rules\n"
        "   - Reusing the same sentence pattern across different books, products, files, or topics does not by itself prove a skill exists.\n"
        "   - Repetition alone is not evidence. Only repeated use backed by stable execution rules may count.\n\n"
        "5. One-time delivery parameters\n"
        "   - Quantity, word count, output language, whether to include code/table/JSON, brevity, formality, or platform-specific formatting should not be extracted if they only serve the current delivery.\n\n"
        "6. Requests that depend on current payload to make sense\n"
        "   - If the supposed skill stops making sense once current code, current data, current article, current book, current project, or current entities are removed, do not extract.\n\n"
        "7. High-frequency tasks without a stable user-defined method\n"
        "   - A user doing similar tasks often does not imply a skill exists.\n"
        "   - Frequency is not evidence unless the USER also defines durable, transferable execution requirements.\n\n"

        "### 5) Task Boundary, Reusability, and Generalization\n"
        "1. Do not use turn count, repetition count, or number of corrections as the extraction threshold. Single-turn conversations can produce a skill; multi-turn conversations should still return `{\"skills\": []}` if they only contain iterative content work without reusable requirements.\n"
        "2. Use the most recent USER turns to identify the active task. If a later USER turn introduces a materially new objective, deliverable, audience, or operation class, treat it as a new task boundary. Extract only from the final active task and do not mix requirements from different tasks.\n"
        "3. Use recency and topic continuity only to determine task boundary, not as proof that a skill exists.\n"
        "4. Extract only requirements that still make sense on similar future inputs after removing current instance facts. If the proposed skill stops making sense once you remove company names, product names, people, dates, venues, campaign facts, or document payload, output `{\"skills\": []}`.\n"
        "5. Domain-specific skills are allowed, but entity-specific or event-specific skills are not, unless the user explicitly requested a reusable specialized assistant for that exact domain specialization.\n"
        "6. Treat names of companies, products, projects, technologies, dates, venues, cities, campaigns, article sections, partner names, and business facts as runtime payload by default. Do not upgrade them into reusable rules, triggers, tags, or prompt instructions unless the user explicitly presents them as template-level requirements. Keep only the reusable task logic, not the case facts.\n"
        "7. Repeat-use check: after de-identification, if this same user is unlikely to reuse the extracted policy/workflow in nearby future tasks, output `{\"skills\": []}`.\n"
        "8. Do not confuse a frequent task category with a skill. A user often doing something does not mean the user has defined a stable reusable protocol for it.\n\n"

        "### 6) No Invention Rule\n"
        "Extract only what is directly supported by USER evidence.\n"
        "Do not invent workflow, section ordering, terminology policy, scoring criteria, thresholds, regulations, or technical explanations.\n"
        "If the user gives constraints but no workflow, do not invent a workflow.\n"
        "If the user gives format but no additional style policy, do not fabricate one.\n"
        "If the user repeatedly invokes a generic capability without defining a stable method, do not upgrade it into a skill.\n\n"

        "### 7) Output Construction Rules\n"
        f"Return JSON as {{\"skills\": [...]}} with at most {max_candidates} item(s).\n"
        "Fields per skill:\n"
        "- name: concise, searchable, and self-explanatory intent+task phrase in the SAME language as the conversation. It should directly express reusable capability, not one-off topic facts, and should avoid vague placeholders.\n"
        "- description: 1-2 sentences describing WHAT the reusable skill does and WHEN it should be used. Avoid case-specific facts.\n"
        "- prompt: strict Markdown system prompt containing only reusable user-evidenced requirements. It MUST include:\n"
        "   - # Role & Objective\n"
        "   - # Communication & Style Preferences\n"
        "   - # Operational Rules & Constraints\n"
        "   - # Anti-Patterns\n"
        "   - # Interaction Workflow (optional, only if explicitly evidenced by USER)\n"
        "   - Keep the prompt focused on the core instructions needed on every run; avoid stuffing long reference material into the prompt.\n"
        "- triggers: 3-5 deduplicated intent phrases that would activate this skill. They must reflect reusable task requests, not one-off entities.\n"
        "- tags: 1-6 canonical keywords in the SAME language as the conversation. Prefer task or domain words over entity names.\n"
        "- examples: 0-2 short, de-identified examples showing the task shape. Do not introduce new facts.\n"
        "- optional resources/files: include only when the USER evidence implies durable bundled artifacts that should live with the skill.\n"
        "   - resources shape: `{\"scripts\": [...], \"references\": [...], \"assets\": [...]}`\n"
        "   - files shape: `{\"scripts/...\": \"...\", \"references/...\": \"...\", \"assets/...\": \"...\"}`\n"
        "   - scripts: only for stable deterministic helpers repeatedly useful for this workflow\n"
        "   - references: only for longer reusable guidance, checklists, schemas, or domain notes directly evidenced by the USER\n"
        "   - assets: only for reusable output templates, placeholders, or small sample artifacts, not large raw payloads\n"
        "   - use safe relative paths under `scripts/`, `references/`, or `assets/` and keep file content concise\n"
        "   - if a resource is emitted, the prompt should mention when to read or run it\n"
        "   - do not duplicate the same long material in both prompt and resources\n"
        "- confidence: float between 0.0 and 1.0, based on how specific and reusable the USER requirements are\n\n"

        "### 8) Confidence Guidance\n"
        "Use high confidence when the USER provides explicit schema, field definitions, mapping rules, calculation logic, strict output constraints, or a detailed SOP, and these clearly appear intended for future similar tasks.\n"
        "Use medium confidence when the USER provides a clear but lighter reusable policy with plausible future reuse value.\n"
        "Use low confidence only when the signal is weak but still specific enough to extract and does not look like mere instance-level delivery parameters.\n"
        "If requirements are not specific enough to execute repeatedly, or look more like current-task parameters than a durable protocol, output `{\"skills\": []}`.\n\n"

        "### 9) Final Emission Check\n"
        "Before emitting a skill, verify all of the following:\n"
        "1. Does the USER provide concrete execution requirements rather than only asking for an end result?\n"
        "2. Are these requirements defining a stable handling policy for future similar tasks rather than only current-task delivery parameters?\n"
        "3. Would the extracted behavior still be useful on similar future inputs?\n"
        "4. Are the major rules traceable to USER turns only?\n"
        "5. Did you avoid copying case-specific facts into reusable rules?\n"
        "6. Is this likely to be reused by this same user in future similar tasks?\n"
        "7. Is this merely a generic capability call such as debugging, coding, data processing, translation, or batch content generation, without a stable user-defined method?\n"
        "8. Is the USER doing more than reusing the same request sentence with different entities or materials?\n"
        "If any answer is NO, output `{\"skills\": []}`.\n\n"

        "### 10) Language Consistency\n"
        "Determine one dominant language from USER text and use it consistently for all textual fields.\n"
        "If dominant language is unclear, return `{\"skills\": []}`.\n\n"

        "### JSON Validity Rules\n"
        "- Escape all newlines within string values as `\\n`.\n"
        "- Escape double quotes within string values properly.\n"
        "- Do not wrap the output in Markdown code blocks.\n"
        "- Return raw JSON string ONLY.\n"
    )


def build_offline_extract_prompt(*, channel: str, max_candidates: int) -> str:
    """Backward-compatible extract prompt dispatcher."""
    _base, mode = parse_offline_channel(channel)
    if mode == EXTRACT_MODE_COMMON:
        return build_offline_extract_prompt_common(channel=channel, max_candidates=max_candidates)
    return build_offline_extract_prompt_specific(channel=channel, max_candidates=max_candidates)


def build_offline_repair_prompt(*, channel: str, max_candidates: int) -> str:
    """Run build offline repair prompt."""
    if not is_offline_channel(channel):
        return ""
    return (
        "You are a JSON output fixer for offline conversation skill extraction.\n"
        "Given DATA and DRAFT, output ONLY strict JSON: {\"skills\": [...]}.\n"
        f"Return at most {max_candidates} skills; if uncertain return {{\"skills\": []}}.\n"
        "No Markdown, no commentary.\n"
        "If input provides 'Primary User Questions' and 'Full Conversation', prioritize the primary section, focus on USER inputs there, and use full conversation only as context reference; assistant/model replies are not skill evidence.\n"
        "Preserve only reusable, de-identified capability/policy/workflow signals.\n"
        "Keep only candidates with clear future repeat-use value for the same target user/team; if repeat-use value is low, return {\"skills\": []}.\n"
        "When multiple events exist, keep only content tied to the dominant event chain and drop unrelated details; if uncertain, prefer dropping.\n"
        "For offline conversation extraction, use USER turns only as skill evidence; ASSISTANT turns are not evidence.\n"
        "If content is primarily knowledge Q&A without durable reusable behavior/policy/workflow, return {\"skills\": []}.\n"
        "Do not preserve assistant/platform artifacts as skill constraints (token limits, output-length caps, model/runtime/tool/API failures, context-window limits) unless the user explicitly asks to enforce them as policy.\n"
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

        "### Focus: Conversation-Derived Candidates\n"
        "Compare user intent evolution, style preferences, anti-patterns, and persona alignment.\n"
        "### Channel-Specific Decision Rules:\n"
        "- MERGE (Continual Alignment): This is highly preferred for user preferences. If the candidate reflects an updated user constraint, a new formatting request, or a correction to a past habit, MERGE it to evolve and overwrite the old constraints in the target skill.\n"
        "- MERGE (Resource Upgrade): If the candidate mainly adds a reusable script, reference note, or template for the same capability, MERGE rather than ADD.\n"
        "- DISCARD: If the candidate represents a transient, session-specific chatting pattern that does not generalize, has low future repeat-use value for this user, or if the existing skill already strictly enforces this behavior.\n"
        "- ADD: ONLY if the user establishes a completely new workflow or distinct persona request not covered by existing profiles and likely to be reused in future interactions.\n"
        "- Keep skills narrow: if two behaviors are adjacent but separable jobs-to-be-done, prefer keeping them as separate skills rather than merging into one broad profile.\n\n"

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

        "### Primary Comparison Axis: User Intent & Persona/Policy Identity\n"
        "- Core Question: Do both skills govern the SAME type of user interaction, formatting task, or persona profile?\n"
        "- RETURN TRUE: If the candidate simply updates constraints, tone preferences, or anti-patterns for an existing objective (e.g., evolving a 'code review' skill with new 'must-not-do' rules derived from recent chats). This is how agent persona evolves.\n"
        "- RETURN FALSE: If the candidate introduces a completely novel task objective that the existing skill was never designed to handle.\n\n"

        "### General Judgment Criteria:\n"
        "1. Penetrate the Wording: Ignore textual variance. Do not return FALSE just because the skill names, triggers, or specific examples use different vocabulary. Focus purely on 'Objective + Deliverable + Operation Class'.\n"
        "2. Incremental Evolution is SAME: If the candidate is an incremental improvement, a bug fix, or a constraint refinement of the existing skill, they share the SAME capability identity.\n"
        "3. Per-user utility view: judge identity under the assumption that retained skills should help the same target user/team in future similar tasks.\n"
        "4. Keep identity narrow: adjacent tasks, neighboring formats, or related deliverables are not the same capability if they imply different execution policies.\n"
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

        "### Fusion Strategy: Conversation-Derived Continual Alignment\n"
        "- Objective: Evolve the agent's persona and interaction policy based on iterative user feedback.\n"
        "- RECENCY BIAS (Crucial): The `candidate_skill` represents the newer user preference. If the candidate explicitly contradicts the `existing_skill` regarding output format, verbosity, or tone, the candidate's rules MUST overwrite the existing ones.\n"
        "- Anti-Pattern Accumulation: Carefully aggregate all 'must-not-do' rules and `# Anti-Patterns` from both sides. Do not lose past negative constraints unless explicitly revoked by the candidate.\n\n"

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
        "- prompt: MUST be cohesive, executable Markdown. Depending on the skill type, structurally merge sections like `# Role & Objective`, `# Constraints & Style`, `# Core Workflow` (or Tool Usage), and `# Anti-Patterns`.\n"
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
