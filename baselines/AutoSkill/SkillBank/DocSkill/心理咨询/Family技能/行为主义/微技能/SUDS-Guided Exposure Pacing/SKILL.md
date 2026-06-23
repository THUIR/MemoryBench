---
id: "76248048-585c-5cef-8059-4b12e8325e9f"
name: "SUDS-Guided Exposure Pacing"
description: "A micro-intervention where the therapist uses real-time SUDS ratings to pace imaginal exposure: pausing only for brief regulation, prompting continuation at SUDS < 90, and reinforcing tolerance at peaks."
version: "0.1.0"
tags:
  - "imaginal exposure"
  - "SUDS"
  - "PTSD"
  - "behavioral activation"
  - "exposure pacing"
  - "行为主义"
  - "profile:psychology::行为主义"
  - "axis:疗法"
triggers:
  - "Client reports SUDS ≥ 70 during memory narration"
  - "Client pauses mid-narrative with visible distress (sweating, tearfulness)"
  - "Therapist observes physiological arousal cues"
examples:
  - input: "Client pauses mid-narrative, sweating, SUDS reported as 100."
    output: "Therapist: 'What’s your SUDS right now?' → Client: '100.' → Therapist: 'You’re doing great — keep going. Remember, it’s just a memory; you’re safe here.'"
    notes: "Prompt occurs within 5 sec of pause; no delay for regulation unless SUDS remains ≥ 90 after 15 sec."
  - input: "Client says 'I can’t go on' after SUDS 70, tearful but oriented."
    output: "Therapist: 'I know how hard that was — you did a great job staying with it so far. Would you like to try continuing from where you left off?'"
    notes: "Reinforcement precedes invitation; avoids pressure while preserving exposure frame."
---

# SUDS-Guided Exposure Pacing

A micro-intervention where the therapist uses real-time SUDS ratings to pace imaginal exposure: pausing only for brief regulation, prompting continuation at SUDS < 90, and reinforcing tolerance at peaks.

## Prompt

Monitor SUDS continuously during imaginal exposure. If client reports SUDS ≥ 70 or shows visible distress (e.g., sweating, tearfulness, pause), immediately check SUDS. If SUDS is < 90 and client is responsive, gently prompt continuation ('You're doing great; keep going') and normalize safety ('It's just a memory—you are safe here'). If SUDS remains ≥ 90 after 10–15 seconds of grounding, briefly validate and recheck; do not extend pause beyond 20 seconds unless dissociation or medical concern is evident. Reinforce effort and tolerance after each segment, especially post-peak.

## Objective

Maintain therapeutic exposure dose while preventing overwhelm via moment-to-moment SUDS-informed timing decisions.
## Applicable Signals

- SUDS rating reported verbally
- Pause longer than 5 seconds during narration
- Autonomic signs: sweating, trembling, rapid breathing, tearfulness

## Contraindications

- Client is dissociated or unresponsive to verbal prompts
- SUDS is unstable due to acute medical issue
- Client explicitly requests stop without rationale

## Intervention Moves

- SUDS check on pause or distress cue
- Brief normalization + safety reminder
- Time-limited encouragement to resume
- Post-segment reinforcement tied to tolerance, not outcome

## Workflow Steps

- Observe for distress cue or spontaneous pause.
- Ask: 'What’s your SUDS right now?' — wait for verbal response.
- If SUDS < 90 and client is oriented: say 'You're doing great; keep going' + 'Remember, it’s just a memory — you’re safe here.'
- If SUDS ≥ 90: hold 10–15 sec, then recheck; if still ≥ 90, offer one breath and recheck once more — then decide whether to continue or pause briefly.
- After resumption or completion of segment, name effort: 'I know how hard that was — you stayed with it.'

## Constraints

- Do not pause longer than 20 seconds unless safety assessment indicates need
- Do not proceed if client is nonverbal or disoriented
- SUDS must be confirmed verbally—not assumed from behavior alone

## Cautions

- Avoid reassurance that minimizes experience (e.g., 'It’s over now')—instead anchor in present safety and agency
- Never override explicit stop request—even if rationale seems insufficient
- If SUDS spikes to 100 and remains there across two checks, consider short break and collaborative re-engagement

## Output Contract

- Client resumes narration within 15 seconds after SUDS check, with no escalation beyond prior peak SUDS value.

## Example Therapist Responses

### Example 1

- Client/Input: Client pauses mid-narrative, sweating, SUDS reported as 100.
- Therapist/Output: Therapist: 'What’s your SUDS right now?' → Client: '100.' → Therapist: 'You’re doing great — keep going. Remember, it’s just a memory; you’re safe here.'
- Notes: Prompt occurs within 5 sec of pause; no delay for regulation unless SUDS remains ≥ 90 after 15 sec.

### Example 2

- Client/Input: Client says 'I can’t go on' after SUDS 70, tearful but oriented.
- Therapist/Output: Therapist: 'I know how hard that was — you did a great job staying with it so far. Would you like to try continuing from where you left off?'
- Notes: Reinforcement precedes invitation; avoids pressure while preserving exposure frame.

## Files

- `references/evidence.md`
- `references/evidence_manifest.json`

## Triggers

- Client reports SUDS ≥ 70 during memory narration
- Client pauses mid-narrative with visible distress (sweating, tearfulness)
- Therapist observes physiological arousal cues

## Examples

### Example 1

Input:

  Client pauses mid-narrative, sweating, SUDS reported as 100.

Output:

  Therapist: 'What’s your SUDS right now?' → Client: '100.' → Therapist: 'You’re doing great — keep going. Remember, it’s just a memory; you’re safe here.'

Notes:

  Prompt occurs within 5 sec of pause; no delay for regulation unless SUDS remains ≥ 90 after 15 sec.

### Example 2

Input:

  Client says 'I can’t go on' after SUDS 70, tearful but oriented.

Output:

  Therapist: 'I know how hard that was — you did a great job staying with it so far. Would you like to try continuing from where you left off?'

Notes:

  Reinforcement precedes invitation; avoids pressure while preserving exposure frame.
