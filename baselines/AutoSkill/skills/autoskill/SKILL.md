---
name: autoskill
description: Manage personal local Agent Skill files as an installable skill manager. Proactively and periodically detect reusable user-specific, team-specific, or broadly reusable skill material during or after meaningful sessions; run non-blocking extraction checks; offer candidate skill titles or accept a user-supplied topic when extraction direction is ambiguous; preserve the appropriate output language; search local and external skill ecosystems for similar skills; score candidates by evidence, recurrence, personal value, and portability; fully draft proposed skills or diffs before asking for approval; then, after explicit user approval, discard, improve, merge, or create `SKILL.md` folders.
---

# Local Skill File Manager

## Purpose

Maintain the user's personal local skill files as a lightweight self-improving memory system. The default goal is not to produce marketplace-ready generic skills; it is to preserve reusable behavior that helps this user, this team, or this workspace in future sessions. A good candidate may encode personal workflow preferences, project conventions, style contracts, tool choices, or review gates that would not be useful to other users, as long as it is reusable for the intended owner and approved.

This skill does not depend on project-specific code, servers, vector stores, databases, or storage layouts. It operates only on ordinary local skill folders:

```text
<skill-root>/
  <skill-name>/
    SKILL.md
    agents/openai.yaml   (optional)
    scripts/             (optional)
    references/          (optional)
    assets/              (optional)
```

Use this skill to decide when a session contains reusable skill material, find whether a similar skill already exists, then discard, improve, merge, or create a local skill. The model should initiate this check when signals appear; it should not wait for the user to ask. The check must stay lightweight and non-blocking unless the user explicitly asks to focus on skill maintenance.

## Related Skill Coordination

This skill owns the lifecycle decision: when to extract, whether to discard, whether to improve or merge, and where to write. Coordinate with nearby skills when they are installed:

- Use `skill-creator` for new skill structure, naming, resource placement, `agents/openai.yaml`, and validation.
- Use `skill-improvement` or equivalent improvement guidance for existing-skill iteration, test prompts, failure analysis, trigger-description tuning, and before/after comparison.
- Use `skill-finder`, `find-skills`, or equivalent discovery tools to search local or external skill ecosystems before creating a duplicate.
- Borrow self-improvement patterns only as decision heuristics: event triage, deduplication, recurrence, priority, value checks, and promotion gates. Do not adopt another skill's storage paths, daemon assumptions, or code structure unless the user asks.
- If those helper skills are unavailable, apply the built-in procedures below. Do not block on missing helper skills.
- Do not let helper skills weaken the extraction boundary: only reusable, user-evidenced capability changes should be saved.

## Safety And Consent

Local skills can influence future agent behavior and may include executable scripts. Treat skill edits as durable behavior changes.

- Do not install, import, or enable third-party skills without user consent.
- Do not add surprising capabilities, hidden network access, credential handling, data exfiltration, or destructive commands.
- If a skill adds scripts or tool integrations, make their purpose visible in `SKILL.md`.
- When editing a skill that may be shared with a team, preserve organization policies and ask before changing security-sensitive behavior.
- Treat each candidate as `personal` by default; mark it `team` or `public` only when the evidence supports that broader audience.
- Do not publish, recommend as broadly reusable, or remove personal scope from a user-specific skill without explicit user approval.
- Before the first persistent learning note or skill write in a new local convention, tell the user what path would be written and ask for approval.
- Do not silently modify this `autoskill` manager itself during routine maintenance. Improve it only when the user explicitly asks to improve this skill.

## Skill Roots

Before writing anything, identify where local skills live.

- Use an explicit user-provided path first.
- Otherwise check common roots such as `${CODEX_HOME}/skills`, `~/.codex/skills`, `./skills`, `.agents/skills`, and any current workspace skill directory containing `*/SKILL.md`.
- If exactly one plausible root exists, use it.
- If multiple plausible roots exist and the target is ambiguous, ask the user which root to maintain.
- Never reorganize unrelated skill roots or edit skills outside the chosen root.

## Trigger Policy

Use a three-layer trigger policy:

1. Silent scan: after each substantive user turn, briefly ask whether the turn contains a reusable personal preference, rule, correction, workflow, failure, or skill-quality issue.
2. Extraction check: when a trigger below fires, classify the experience, assign evidence and value, search for similar skills, and test it against the extraction boundary.
3. Write/update: only edit local skill files after the candidate passes the boundary, the target skill root is clear, and the user approves the exact change.

The model should proactively initiate scans and extraction checks. Do not ask the user "should I check for a skill?" Ask only when the target root is ambiguous, the edit would overwrite uncertain behavior, or the user must approve an external install or sensitive script.

## Candidate Lifecycle

Keep the lifecycle separate from any particular storage system: observe a signal, optionally ask the user to choose a candidate title/topic, draft the candidate, de-duplicate by pattern, decide `discard`/`keep_note`/`improve`/`merge`/`create`, show the complete proposed skill or diff, then apply the smallest approved change and validate.

De-duplicate by task family, trigger, tools, failure mode, output contract, and target skill rather than exact wording. Do not create a private database, daemon, scheduler, or hidden background store as part of this skill.

## Title Selection Gate

Before full extraction, when the reusable topic is ambiguous or there are several plausible skills, show 2-5 concise reusable-capability titles with one-line evidence reasons plus `none of these` and `custom topic`. If the user chooses a title or enters a topic, treat it as direction only: re-run the extraction boundary and similar-skill search for that direction, discard it if it fails, or show the complete proposed `SKILL.md`/diff for final approval if it passes. If the user chooses `none of these`, discard or keep a non-persistent note; do not write files.

## Language Consistency

For new skills, write candidate titles, proposed `SKILL.md`, `agents/openai.yaml`, and small resources in the dominant language of the user evidence; Chinese input produces Chinese skills, English input produces English skills. For updates or merges, keep the target skill's dominant language unless the user explicitly asks to translate it; if mixed evidence makes language ambiguous, ask before drafting. Do not default extracted skill content to English.

## Background Execution

Skill extraction and maintenance must not block the user's main task.

- Treat extraction checks, similar-skill search, candidate drafting, and trigger-eval preparation as background maintenance work whenever possible.
- Background work may prepare candidates, find similar skills, and draft diffs, but it must not write, update, delete, install, or enable skills without user confirmation.
- Continue the primary user request first; do not make the user wait for skill extraction unless the user explicitly asked to focus on skill maintenance.
- Surface background results only when there is an actionable candidate decision, proposed file diff, or clarification/consent question.
- Run at most one background skill-maintenance job per active conversation unless the user asks for a batch; queue or coalesce extra signals.
- Do not start expensive searches, broad evals, or large rewrites in the foreground. Use lightweight checks first, then defer deeper validation to a natural pause or explicit maintenance pass.
- If the runtime cannot actually run background work, emulate it by deferring the maintenance check until after the current answer is complete or the next natural pause.
- Never block delivery of the user's requested work just to finish candidate extraction, unless the requested work is skill maintenance itself.

## Confirmation Gate

User confirmation is required before any skill file is created, updated, deleted, imported, installed, enabled, or materially rewritten. Draft first, ask second: after any title/topic selection, never ask "should I add/update a skill?" until the proposed content or change is already written out for review.

For `create`, show before writing:

- proposed skill name and target path
- intended audience: `personal`, `team`, or `public`, plus portability limits
- why the candidate passed the reusable-skill boundary
- evidence level, recurrence signal, priority, and value signal
- similar skills checked and why this is not a duplicate
- complete proposed `SKILL.md` content
- complete proposed `agents/openai.yaml` and every proposed script, reference, or asset text when such files are small enough to review inline; for large assets, show the exact file list, purpose, provenance, and generated diff or manifest

For `improve` or `merge`, show before writing:

- exact target skill path
- decision type: `improve` or `merge`
- why the change belongs in that existing skill
- evidence level, recurrence signal, priority, and value signal
- a complete unified diff, or complete before/after text for every changed section when a unified diff is unavailable
- every file that would be added, modified, deleted, or left untouched
- validation plan or command to run after approval

Ask for a clear yes/no approval only after showing the full proposed artifact or diff. If the user does not approve, do not edit the skill; report the candidate as deferred or discarded.

## Immediate Triggers

Run an extraction check immediately, or at the next natural pause if the user is waiting for the main task, when any of these happen:

- The user corrects, rejects, or refines the model's approach in a way that should affect future similar tasks.
- The user gives a durable preference, output contract, workflow, naming rule, tool rule, or quality gate.
- A command, script, integration, or workflow fails and the session discovers a reusable fix.
- The agent repeats non-trivial setup, scripting, transformation, or validation work that should become a reusable resource.
- A similar local skill under-triggered, over-triggered, or produced incomplete guidance.
- The session reveals a missing reference, template, script, or checklist that would prevent future repeated effort.
- The user uses future-oriented language such as "remember this as a skill", "save this workflow", "update the local skill", "next time, do it this way", "this is my standard process", or "create a skill from this conversation".

Still treat extraction as a check, not a requirement: no skill change is often the correct outcome.

Do not extract when the user says the rule is temporary, asks not to remember it, or only wants a one-time answer.

## Scheduled Checks

Use scheduled checks to catch gradual learning that no single turn makes obvious:

- Conversation-length check: after roughly 6 substantive user messages, 12 total turns, or 2-3 distinct task attempts since the last check.
- Token/volume check: after a long chunk of new context, especially when the conversation may soon be summarized or compacted.
- Task-boundary check: when a deliverable is completed, a debugging loop ends, a plan is accepted, or the user switches to a new task.
- Session-end check: before the final response of a substantial session, review whether anything should be discarded, improved, merged, created, or noted.

Keep scheduled checks lightweight. They should usually happen silently and only surface to the user when there is an actionable decision or a needed clarification.

## Debounce And Batching

Prevent noisy repeated extraction:

- Do not re-check the same signal repeatedly in one session.
- Batch multiple weak signals until a task boundary or scheduled check.
- Create or update at most one skill per check unless the user explicitly asks for a batch.
- Prefer `keep_note` or `discard` for borderline signals until repetition strengthens the evidence.
- If a candidate is close but not yet reusable enough, remember the rationale in the completion note instead of creating a skill.
- Coalesce simultaneous triggers into one background maintenance pass.
- When multiple candidates compete, handle the highest-priority repeated failure or user-confirmed preference first.

## Experience Triage

Before changing skills, classify the session experience. Durable categories are `error`, `correction`, `best_practice`, `knowledge_gap`, and `preference`. `one_off_result` means the session produced useful work but no durable process change.

Only durable categories can become skill changes, and only after passing the extraction boundary. One-off results should not be promoted.

## Value And Priority Gate

- Priority `P0`: prevents unsafe, destructive, privacy-sensitive, or repeatedly failing behavior.
- Priority `P1`: prevents a significant recurring mistake, missed trigger, bad merge, or expensive repeated workflow.
- Priority `P2`: improves quality, speed, or clarity for a recurring task family.
- Priority `P3`: convenience or style improvement with limited evidence.

Promote by durable value, not novelty. Value must be explainable as reliability, safety, speed, quality, consistency, or reduced repeated work. If no value dimension is clear, discard or keep a non-persistent note.

Change one behavioral lever at a time when improving an existing skill: trigger wording, workflow step, validation gate, resource placement, or safety constraint.

## Promotion Rules

Do not turn every experience into a skill edit. Promote experiences deliberately:

- Promote immediately when the user explicitly says the rule should apply next time.
- Promote immediately when a correction prevents a serious repeated failure, unsafe action, or destructive workflow.
- Promote after repetition when the same error, correction, or best practice appears across multiple similar tasks. As a default, require 2 distinct tasks or 3 comparable uses for assistant-inferred practices.
- Merge into an existing skill when the experience refines a known capability.
- Create a new skill only when the experience reveals a distinct reusable capability.
- Keep as a note or completion summary, not a skill, when the evidence is useful but not yet reusable enough.

When using a local learning-note convention such as `.learnings/`, `MEMORY.md`, or similar, record non-promoted experiences there only if the user or environment already supports that convention. Do not invent a new memory system inside this skill unless the user asks.

## Experience Record Shape

When a learning note or improvement rationale is needed, use a compact structure:

```text
type: error | correction | best_practice | knowledge_gap | preference
status: candidate | deferred | approved | applied | discarded
audience: personal | team | public
summary: one sentence
source: user_feedback | command_error | task_result | review
context: task family, relevant files/tools, and what happened
lesson: reusable rule or missing capability
pattern_key: stable phrase for deduplicating similar experiences
evidence_level: strong | medium | weak
recurrence: first_seen | repeated | user_confirmed
priority: P0 | P1 | P2 | P3
value_signal: reliability | safety | speed | quality | consistency | reduced_rework
suggested_action: discard | improve <skill> | merge <skill> | create <skill> | keep_note
sensitivity: public | private | contains_sensitive_details
```

Redact secrets, personal data, credentials, private URLs, and customer-specific details before storing any note or skill content.

## When To Improve Existing Skills

Prefer improving an existing skill over creating a new one when the session reveals a quality issue in a skill that already exists.

Improve a skill when it under-triggers, over-triggers, gives incomplete guidance, causes repeated work, memorizes one case instead of the reusable pattern, or is too bloated for the value it provides.

Do not "improve" a skill just to add topical payload from the current session. Improvement must increase future reuse quality.

## Extraction Boundary

Extract only reusable capabilities. The boundary is future reuse, not topic similarity and not session length.

Extract when all tests pass:

- User-evidenced: each major rule comes from user instructions, corrections, confirmations, or stable preferences.
- Reusable: the rule applies to future tasks of the same kind after removing case-specific details.
- Owner-valuable: the rule improves future behavior for the user, team, or workspace even if it is not generally useful to strangers.
- Non-obvious: the skill captures workflow, policy, constraints, tool usage, format, or quality checks that a general assistant may not infer reliably.
- Actionable: another agent can follow the skill without reading the original conversation.
- Worth saving: storing it improves future behavior more than it increases skill-library noise.

Do not extract when any test fails:

- The session only produced a one-off answer, artifact, bug fix, or factual explanation.
- The candidate is just topic payload: names, addresses, links, exact dates, tickets, project IDs, account details, budgets, or current-session deliverables.
- The candidate is generic advice such as "be accurate", "be concise", "write clearly", or "check your work" without a specific reusable workflow or output contract.
- The rule appears only in assistant output and was not requested, accepted, corrected, or reinforced by the user.
- De-identification removes the useful substance.
- A similar local skill already covers it and the candidate adds no durable user-specific improvement.
- The candidate only reflects what the assistant happened to do successfully once.
- The apparent pattern comes from silence, politeness, or lack of user correction rather than evidence.
- The candidate would make an existing skill broader without improving a concrete future behavior.
- The candidate frames a personal or project-specific preference as a universal best practice without labeling its intended audience.

Decision line: this-instance content -> do not extract; reusable method, preference, workflow, output contract, tool rule, or quality gate -> consider extraction.

## Evidence Levels

Rank candidate evidence before saving:

- Strong evidence: explicit user instruction, correction, rejection, reusable workflow, stable preference, or repeated feedback.
- Medium evidence: user confirms an assistant-proposed process or asks to make the current approach the default.
- Weak evidence: assistant-authored structure, one successful answer, inferred preference, or topical similarity.

Save from strong evidence. Save from medium evidence only when the reusable boundary is clear. Do not save from weak evidence unless the user explicitly asks to turn it into a skill.

## Pre-Edit Memory Check

Before editing a local skill, search for prior related experience:

- existing skills with similar names, descriptions, triggers, or workflows
- existing resource files that already solve the repeated work
- local notes or project memory files if the environment already uses them
- recent failures, corrections, or best practices mentioned in the current session

Use this check to avoid re-learning the same lesson, duplicating skills, or ignoring known constraints.

## Candidate Shape

When extraction is warranted, form one candidate skill at a time:

- `name`: lowercase letters, digits, and hyphens; short and capability-specific.
- `description`: state what the skill does and exactly when it should be used; this is the primary trigger surface.
- `audience`: `personal`, `team`, or `public`; default to `personal` for user-specific reuse.
- `instructions`: concise imperative guidance for future agents.
- `triggers`: 3-5 phrases a user might say that should invoke the skill.
- `resources`: optional scripts, references, or assets only when they materially improve reuse.

Remove case details. Keep reusable HOW, not one-off WHAT.

Before writing the candidate, capture the domain context just enough to avoid generic skills:

- task family and job-to-be-done
- expected input types
- expected output or deliverable
- important tools, formats, or constraints
- success criteria or failure modes

Do not include domain context as payload unless it changes future behavior.

## Similar Skill Search

Search before creating anything.

1. Identify the candidate's domain, task, output type, tools, and likely synonyms. Build 2-3 short queries such as `<domain> <task>`, `<tool> <output>`, and `<failure-mode> workflow`.
2. Search local skills first:

```bash
rg --files -g 'SKILL.md' <skill-root>
rg -n "<keyword|task|output-type>" <skill-root>
```

3. Inspect likely local matches: frontmatter `name`/`description`, workflow, triggers, resources, and success criteria. Compare by task family, trigger, tools, failure mode, output contract, and audience.
4. If a local `skill-finder`, `find-skills`, or equivalent discovery tool is installed, use it to broaden the local/external search. Treat results as similarity evidence, not an automatic merge/install decision.
5. When external ecosystem search is requested, duplication risk is high, or the candidate is meant to be public, check well-known sources before creating a new skill. For personal skills, external search is evidence for avoiding duplicates, not a popularity test:
   - browse `https://skills.sh/` or its leaderboard for popular/battle-tested options
   - run `npx skills find <query>` with the best 1-2 queries
   - try alternate terms when the first query misses, e.g. `deploy` vs `deployment` or `pr review` vs `code review`
6. Verify external candidates before recommending them: prefer high install counts, reputable sources, and active source repositories; be cautious with low-install or unknown-author skills.
7. Present external matches with name, purpose, source/quality signal, link, and install command. Do not install, import, overwrite, or merge external skills without explicit user consent.
8. If no suitable skill exists, say so and continue with `create` only if the candidate passes the extraction boundary.

## Decision Rules

Choose one outcome.

`discard` when:

- The candidate fails the extraction boundary.
- It is useful only for the current session.
- It duplicates an existing skill without durable improvement.
- It is mostly assistant-invented or unsupported by user evidence.
- It would create a vague, generic, or low-signal skill.

`improve` when:

- An existing skill has the right identity but failed in use.
- The issue is trigger accuracy, unclear instructions, missing validation, bloated guidance, stale details, or missing reusable resources.
- The session provides evidence for a better general version of that same skill.
- No new standalone capability is needed.
- The improvement can be expressed as a small, evaluable change to the existing skill.

`merge` when:

- The candidate and an existing local skill solve the same job-to-be-done.
- The deliverable, audience, tool context, operation type, and success criteria are substantially aligned.
- The candidate adds reusable constraints, clearer triggers, stronger checks, better examples, or reusable resources.
- Differences are mostly wording, names, examples, or case details.

`create` when:

- The candidate passes the extraction boundary.
- No local skill covers the same capability.
- Its job-to-be-done, deliverable, audience, tool context, workflow, or success criteria materially differ from existing skills.
- It is likely to be reused by the intended user, team, or public audience enough to justify a new skill folder.
- It has a clear trigger surface and does not depend on the original session context.

Prefer `discard` over creating vague skills. Prefer `improve` for skill-quality failures. Prefer `merge` over creating duplicate skills. Prefer `create` only for a distinct reusable capability.

Decision outcomes before confirmation:

- `discard`: may be reported without confirmation because no file changes occur.
- `keep_note`: requires confirmation if it writes to any memory file; otherwise may be included in the completion note.
- `improve`, `merge`, `create`: always require confirmation before file changes.

## Improvement Loop

Use this loop for non-trivial changes to an existing local skill.

1. Diagnose the failure.
   - Identify whether the issue is trigger miss, false trigger, unclear instructions, missing workflow, weak validation, duplicated content, stale content, or missing reusable resources.
   - Read enough of the current skill and any relevant resources to understand why the failure happened.
   - Separate failure analysis from rewriting: first name the failure mode, then choose the smallest skill change that addresses it.

2. Preserve a baseline when useful.
   - If the skill is version-controlled, rely on the existing VCS diff.
   - If there is no VCS and the edit is risky, copy the original skill folder to a temporary sibling or workspace snapshot before editing.
   - Do not create permanent changelogs or process files inside the skill.

3. Generalize from the feedback.
   - Fix the broader pattern, not only the example that failed.
   - Explain the reason behind important instructions so future agents can adapt instead of following brittle rules.
   - Avoid rigid all-caps rules when a short rationale would guide behavior better.
   - Change one lever at a time unless the user approved a broader rewrite.

4. Keep the skill lean.
   - Remove instructions that do not affect outcomes.
   - Move bulky details into `references/` only if they are genuinely reused.
   - Add scripts only when repeated deterministic work appears across examples.

5. Validate with realistic prompts.
   - Create 3-8 lightweight prompts for ordinary improvements.
   - Include both should-trigger and should-not-trigger cases when the description changed.
   - Prefer realistic near-misses over obviously irrelevant negative cases.
   - For objective skills, include clear expected outputs or checks; for subjective skills, use human review criteria.
   - Prefer external signals: user feedback, task outputs, tests, or review notes. Do not rely on self-critique alone for major rewrites.
   - Compare before/after behavior when possible, especially for trigger descriptions and over-trigger risk.

6. Iterate.
   - Apply the smallest general fix.
   - Re-check the prompts.
   - Stop when the user is satisfied, failures are resolved, or further edits are no longer meaningfully improving the skill.

## Evolution Guardrails

Self-improvement can drift if the agent keeps rewriting from its own guesses. Use these guardrails:

- Tie every change to a concrete failure, user correction, test case, or observed repeated work.
- Keep traceability: be able to say which experience caused the change and why it was promoted.
- Keep before/after behavior comparable; if possible, rerun the same prompts after editing.
- Preserve the skill's core identity unless the user explicitly wants a new direction.
- Avoid adding broad meta-rules that make the skill trigger everywhere.
- Prefer small, reversible edits over large rewrites.
- Review and prune stale or over-specific rules when they stop matching current user behavior.
- Do not keep self-editing in a loop because a new idea feels plausible. Require evidence or user approval for each iteration.
- If two improvement rounds do not improve outcomes, stop and ask for user judgment.

## Acceptance Checks

Before asking the user to approve a skill write, ensure it is self-contained, minimal, non-duplicative, confirmable, validatable, and privacy-safe. The user must see the exact target path plus the complete proposed skill content or complete diff before the approval question.

## Merge Procedure

When merging:

1. Read the target `SKILL.md` and relevant resources.
2. Preserve existing user-authored constraints and resources unless explicitly replacing them.
3. Add only portable, user-evidenced improvements.
4. Merge semantically; do not append duplicate sections or near-identical bullets.
5. Keep `description` strong enough to trigger the skill in future sessions.
6. Move lengthy details into `references/` only when needed.
7. Put deterministic repeated operations in `scripts/` only when they will actually be reused.
8. Keep unrelated resource files untouched.

After editing, validate if a validator is available. If `skill-creator` tooling is installed, run:

```bash
python3 <skill-creator>/scripts/quick_validate.py <path/to/skill-folder>
```

Do not perform the edit until the user has approved the proposed target and diff.

## Trigger Description Optimization

The frontmatter `description` is the most important trigger surface. After creating or materially improving a skill, review it separately.

A strong description:

- Says what the skill does.
- Says when to use it, including user intents and task contexts.
- Is specific enough to avoid generic over-triggering.
- Is broad enough to catch realistic paraphrases and casual requests.
- Mentions file types, tools, domains, or deliverables only when they materially affect triggering.

Use a small trigger eval set when the skill's scope is subtle:

```json
[
  {"query": "realistic user request that should trigger", "should_trigger": true},
  {"query": "near-miss request that should not trigger", "should_trigger": false}
]
```

Include near-miss negatives that share vocabulary with the skill but require a different capability. Avoid easy negatives that prove nothing.

When tuning the description, generalize from failures rather than listing every observed phrase. The description should make the skill easy to discover without becoming a keyword dump.

## Create Procedure

When creating a new skill:

1. Choose a short hyphen-case name under 64 characters.
2. Create `<skill-root>/<skill-name>/SKILL.md`.
3. If `skill-creator` tooling is available, prefer:

```bash
python3 <skill-creator>/scripts/init_skill.py <skill-name> --path <skill-root>
```

4. Write only the required skill content:
   - frontmatter with `name` and `description`
   - concise body instructions
   - optional `agents/openai.yaml` metadata when supported
   - optional `scripts/`, `references/`, or `assets/` only when useful

5. Do not create README files, changelogs, install guides, or extra process notes unless the skill itself needs them to function.
6. Validate with available tooling or manually check YAML frontmatter, naming, and trigger clarity.

Do not create the folder or write files until the user has approved the proposed skill.

## Skill Writing Standards

Borrow these skill-creator principles:

- Keep the skill concise; include only context a future agent needs.
- Put all trigger-critical "when to use" language in the frontmatter `description`.
- Use imperative instructions.
- Prefer reusable examples over long explanations.
- Use progressive disclosure: keep `SKILL.md` lean and move large references into `references/`.
- Add scripts only for repeated, deterministic, or error-prone operations.
- Add assets only when they are meant to be reused in outputs.

## Completion Note

After managing local skills, report the decision, target path or "no file changed", intended audience and portability limits, title/topic selected if any, approval status, reuse-boundary reason, similar skills checked, validation run, changed sections/files for updates, and whether maintenance completed synchronously or was deferred.
