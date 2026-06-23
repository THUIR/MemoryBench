---
id: "611c72f6-2e06-5a28-8736-a34661e8519a"
name: "Prolonged Exposure Protocol"
description: "A structured, evidence-based macro-level treatment framework for PTSD involving repeated imaginal and in vivo exposure to trauma memories and avoided stimuli."
version: "0.1.0"
tags:
  - "PTSD"
  - "exposure"
  - "trauma_recovery"
  - "behaviorism"
  - "manualized"
  - "行为主义"
  - "profile:psychology::行为主义"
  - "axis:疗法"
  - "kind:parent"
triggers:
  - "Client has confirmed PTSD diagnosis"
  - "Client is psychologically stable enough for exposure work"
  - "Client consents to trauma memory reprocessing"
examples:
  - input: "Client endorses daily flashbacks, avoids driving past earthquake site, reports panic when hearing sirens"
    output: "Therapist introduces PE rationale, co-constructs in vivo hierarchy (e.g., drive 1 block near site → sit in car at site → walk 5 min there), assigns first exposure task with SUDS tracking"
    notes: "First in vivo assignment prioritizes control and predictability"
---

# Prolonged Exposure Protocol

A structured, evidence-based macro-level treatment framework for PTSD involving repeated imaginal and in vivo exposure to trauma memories and avoided stimuli.

## Prompt

Deliver as a manualized 8–15 session protocol: begin with psychoeducation and breathing retraining; conduct imaginal exposure (recounting trauma aloud with present-tense detail) for 30–45 min per session, followed by processing; assign in vivo exposure homework targeting real-world avoided situations; review adherence and distress ratings weekly; monitor habituation across sessions using SUDS. Maintain fidelity via session checklists and audio review.

## Objective

Reduce PTSD symptoms through habituation and emotional processing of trauma memories
## Applicable Signals

- Client reports persistent avoidance of trauma reminders
- Client endorses intrusive memories or flashbacks
- Client shows physiological reactivity during trauma narrative

## Contraindications

- Active suicidal ideation without safety plan
- Acute dissociation or psychosis
- Client refuses exposure components

## Intervention Moves

- Psychoeducation about PTSD and PE rationale
- Breathing retraining for arousal regulation
- Imaginal exposure with present-tense recounting
- In vivo exposure hierarchy development and practice
- Processing time after imaginal exposure

## Workflow Steps

- 1. Assess eligibility and obtain informed consent
- 2. Conduct baseline assessment (e.g., CAPS-5, PCL-5)
- 3. Deliver psychoeducation and breathing retraining (Sessions 1–2)
- 4. Introduce and conduct imaginal exposure (Sessions 3–10+)
- 5. Introduce and assign in vivo exposure (Sessions 3–15)
- 6. Review progress, adjust hierarchy, reinforce gains (weekly)

## Constraints

- Must not proceed to imaginal exposure before establishing grounding skills and therapeutic alliance
- Imaginal exposure must be conducted within client's window of tolerance—pause if dissociation or extreme distress occurs
- In vivo exposure must be collaboratively graded and never coercive

## Cautions

- Monitor for emotional flooding or retraumatization
- Avoid exposure if client lacks current safety (e.g., ongoing abuse)
- Do not use with clients who cannot reliably self-report distress (e.g., severe cognitive impairment)

## Output Contract

- Client completes 8–15 sessions with sustained reduction in avoidance and hyperarousal symptoms per CAPS-5 or PCL-5

## Example Therapist Responses

### Example 1

- Client/Input: Client endorses daily flashbacks, avoids driving past earthquake site, reports panic when hearing sirens
- Therapist/Output: Therapist introduces PE rationale, co-constructs in vivo hierarchy (e.g., drive 1 block near site → sit in car at site → walk 5 min there), assigns first exposure task with SUDS tracking
- Notes: First in vivo assignment prioritizes control and predictability

## 子技能目录
- [Imaginal Exposure Session Scaffold](心理咨询/Family技能/行为主义/二级技能/Imaginal Exposure Session Scaffold/SKILL.md) ｜ 适用：A structured session workflow for delivering imaginal exposure to trauma memories, including memory anchoring, sensory-emotional elaboration, and in-session habituation tracking.

## 选用规则（二级技能目录）
- 当目标、阶段或方法更接近 `Imaginal Exposure Session Scaffold` 时，优先调用它。 线索：Client has confirmed PTSD diagnosis, Client is stabilized and consented to exposure, Trauma memory is accessible and narratable, Client has confirmed PTSD diagnosis and coherent trauma memory, Client is emotionally regulated and has consented to exposure

## Files

- `references/children_manifest.json`
- `references/children_map.md`
- `references/evidence.md`
- `references/evidence_manifest.json`

## Triggers

- Client has confirmed PTSD diagnosis
- Client is psychologically stable enough for exposure work
- Client consents to trauma memory reprocessing

## Examples

### Example 1

Input:

  Client endorses daily flashbacks, avoids driving past earthquake site, reports panic when hearing sirens

Output:

  Therapist introduces PE rationale, co-constructs in vivo hierarchy (e.g., drive 1 block near site → sit in car at site → walk 5 min there), assigns first exposure task with SUDS tracking

Notes:

  First in vivo assignment prioritizes control and predictability
