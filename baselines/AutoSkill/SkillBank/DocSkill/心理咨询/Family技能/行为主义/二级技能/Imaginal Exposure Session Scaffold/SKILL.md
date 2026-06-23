---
id: "123f9a9f-fb4d-50d0-8c16-5d58d2d38a43"
name: "Imaginal Exposure Session Scaffold"
description: "A structured session workflow for delivering imaginal exposure to trauma memories, including memory anchoring, sensory-emotional elaboration, and in-session habituation tracking."
version: "0.1.0"
tags:
  - "PTSD"
  - "trauma"
  - "exposure"
  - "behaviorism"
  - "homework"
  - "exposure_therapy"
  - "SUDS"
  - "行为主义"
  - "profile:psychology::行为主义"
  - "axis:疗法"
  - "kind:parent"
triggers:
  - "Client has confirmed PTSD diagnosis"
  - "Client is stabilized and consented to exposure"
  - "Trauma memory is accessible and narratable"
  - "Client has confirmed PTSD diagnosis and coherent trauma memory"
  - "Client is emotionally regulated and has consented to exposure"
  - "Session time allows ≥45 minutes for exposure work"
examples:
  - input: "Client begins hesitantly: 'It was loud... and then things fell.'"
    output: "Therapist responds: 'Let’s go back to the very first moment you knew something was wrong — where were you? What did you hear *right then*?'"
    notes: "Anchors to onset; invites sensory specificity without interpretation."
  - input: "Client states: 'I was scared.'"
    output: "Therapist responds: 'What was the fear like in your body just then? Where did you feel it? Was there a thought that came with it?'"
    notes: "Elaborates emotion somatically and cognitively, staying within exposure frame."
  - input: "Client reports SUDS 80 pre-exposure; narrates accident memory with visible distress; pauses at impact; SUDS peaks at 100."
    output: "Therapist uses containment phrase, invites continuation, obtains SUDS 70 post-narration, then guides second repetition — SUDS drops to 40 by end."
    notes: "Habituation evidenced by 60-point SUDS drop and reduced somatic reactivity."
  - input: "Client completes first narration (SUDS 90 → 60); expresses doubt about repeating."
    output: "Therapist normalizes difficulty, affirms effort, collaboratively checks readiness — client agrees to try again; second repetition yields SUDS 60 → 30."
    notes: "Success hinges on collaborative pacing, not pressure."
---

# Imaginal Exposure Session Scaffold

A structured session workflow for delivering imaginal exposure to trauma memories, including memory anchoring, sensory-emotional elaboration, and in-session habituation tracking.

## Prompt

Begin by anchoring the trauma memory at the earliest moment of awareness (e.g., 'when you first realized the earthquake was happening'). Prompt the client to narrate in present tense, specifying location, people present, visual/auditory/tactile sensations, physiological responses, thoughts, and emotions. After each retelling, invite deeper sensory and emotional detail to promote habituation and mastery. Record the final version for between-session listening.

## Objective

Reduce PTSD-related anxiety through controlled, repeated trauma memory activation and processing
## Applicable Signals

- Client avoids trauma narrative but tolerates brief mention
- Client reports intrusive memories or flashbacks
- Client expresses desire to 'get past' the memory
- Client reports vivid, intrusive trauma memory
- Client shows physiological arousal (e.g., sweating, tearfulness) during memory recall
- SUDS stabilizes or declines across repetitions

## Contraindications

- Acute suicidality or dissociation present
- Client lacks distress tolerance skills
- No psychoeducation or rationale provided yet
- Client is actively suicidal or experiencing acute dissociation
- Client lacks a current safety plan or grounding skills
- SUDS remains ≥80 and rising despite containment support

## Intervention Moves

- Anchor memory at onset of threat awareness
- Prompt multisensory and emotional detail iteratively
- Normalize distress as part of habituation process
- Record final narration with client consent for homework
- SUDS anchoring before/after each repetition
- Present-tense memory narration prompting
- Containment reframing ('It's a memory; you are safe now')
- Normalization and reinforcement after completion

## Workflow Steps

- Confirm stabilization, informed consent, and shared rationale for imaginal exposure
- Anchor the trauma memory at the earliest point of threat awareness
- Guide client to narrate the event in present tense, covering context (where, who), sensory input (what seen/heard/felt), bodily sensations, thoughts, and emotions
- After initial narration, prompt progressively richer sensory and emotional detail across 2–3 retellings
- Observe and label habituation cues (e.g., reduced voice tremor, longer pauses, calmer breathing)
- Record the most complete, emotionally engaged retelling with client permission for homework
- Assess readiness: confirm stabilization, consent, and session time allocation.
- Obtain baseline SUDS rating.
- Instruct client to narrate the trauma memory aloud in present tense, from start to finish.
- Monitor SUDS every 60–90 seconds; note hot spots and pause only for brief containment if needed.
- Upon completion, obtain SUDS; if ≥45 min remains and SUDS > 30, initiate second repetition.
- Repeat full memory at least once more; track SUDS reduction across repetitions.

## Constraints

- Must not proceed if client dissociates or becomes actively suicidal during anchoring
- Therapist must pause and ground before continuing if SUDS > 7/10 mid-narrative
- No interpretation or cognitive reframing during exposure phase
- Total exposure duration must be ≥45 minutes
- Memory must be narrated fully and chronologically both times
- No interpretation, reassurance, or cognitive restructuring during exposure

## Cautions

- Avoid leading questions that distort memory content
- Do not interrupt narrative flow to correct factual inaccuracies
- Monitor for avoidance markers (e.g., vagueness, time-skipping, humor) and gently redirect
- Avoid leading questions or filling memory gaps for client
- Do not interrupt narrative flow unless safety or dissociation emerges
- Never proceed to next repetition if client is dissociated or ungrounded

## Output Contract

- One audio-recorded, therapist-verified, detailed, present-tense trauma narrative — containing location, people, sensory details, bodily sensations, thoughts, and emotions — delivered with sustained emotional engagement and suitable for client self-administered homework listening.
- Client completes ≥2 full repetitions of the trauma memory within one session, with SUDS reduction ≥30 points between first and last rating, and verbalizes capacity to tolerate the memory.

## Example Therapist Responses

### Example 1

- Client/Input: Client begins hesitantly: 'It was loud... and then things fell.'
- Therapist/Output: Therapist responds: 'Let’s go back to the very first moment you knew something was wrong — where were you? What did you hear *right then*?'
- Notes: Anchors to onset; invites sensory specificity without interpretation.

### Example 2

- Client/Input: Client states: 'I was scared.'
- Therapist/Output: Therapist responds: 'What was the fear like in your body just then? Where did you feel it? Was there a thought that came with it?'
- Notes: Elaborates emotion somatically and cognitively, staying within exposure frame.

### Example 3

- Client/Input: Client reports SUDS 80 pre-exposure; narrates accident memory with visible distress; pauses at impact; SUDS peaks at 100.
- Therapist/Output: Therapist uses containment phrase, invites continuation, obtains SUDS 70 post-narration, then guides second repetition — SUDS drops to 40 by end.
- Notes: Habituation evidenced by 60-point SUDS drop and reduced somatic reactivity.

## 子技能目录
- [SUDS-Guided Exposure Pacing](心理咨询/Family技能/行为主义/微技能/SUDS-Guided Exposure Pacing/SKILL.md) ｜ 适用：A micro-intervention where the therapist uses real-time SUDS ratings to pace imaginal exposure: pausing only for brief regulation, prompting continuation at SUDS < 90, and reinforcing tolerance at peaks.

## 选用规则（微技能目录）
- 当目标、阶段或方法更接近 `SUDS-Guided Exposure Pacing` 时，优先调用它。 线索：Client reports SUDS ≥ 70 during memory narration, Client pauses mid-narrative with visible distress (sweating, tearfulness), Therapist observes physiological arousal cues, imaginal exposure, SUDS

## Files

- `references/children_manifest.json`
- `references/children_map.md`
- `references/evidence.md`
- `references/evidence_manifest.json`

## Triggers

- Client has confirmed PTSD diagnosis
- Client is stabilized and consented to exposure
- Trauma memory is accessible and narratable
- Client has confirmed PTSD diagnosis and coherent trauma memory
- Client is emotionally regulated and has consented to exposure
- Session time allows ≥45 minutes for exposure work

## Examples

### Example 1

Input:

  Client begins hesitantly: 'It was loud... and then things fell.'

Output:

  Therapist responds: 'Let’s go back to the very first moment you knew something was wrong — where were you? What did you hear *right then*?'

Notes:

  Anchors to onset; invites sensory specificity without interpretation.

### Example 2

Input:

  Client states: 'I was scared.'

Output:

  Therapist responds: 'What was the fear like in your body just then? Where did you feel it? Was there a thought that came with it?'

Notes:

  Elaborates emotion somatically and cognitively, staying within exposure frame.

### Example 3

Input:

  Client reports SUDS 80 pre-exposure; narrates accident memory with visible distress; pauses at impact; SUDS peaks at 100.

Output:

  Therapist uses containment phrase, invites continuation, obtains SUDS 70 post-narration, then guides second repetition — SUDS drops to 40 by end.

Notes:

  Habituation evidenced by 60-point SUDS drop and reduced somatic reactivity.
