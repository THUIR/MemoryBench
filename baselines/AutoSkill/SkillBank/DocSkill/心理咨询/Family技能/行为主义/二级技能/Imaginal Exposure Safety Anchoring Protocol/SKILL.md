---
id: "6a4b496c-2160-52b2-a476-a5b985338d3a"
name: "Imaginal Exposure Safety Anchoring Protocol"
description: "A safety-critical micro-intervention where the therapist delivers two standardized verbal anchors—'It's just a memory' and 'You are safe here in the office'—during high-distress moments to prevent dissociation and reinforce present-moment orientation."
version: "0.1.0"
tags:
  - "imaginal exposure"
  - "PTSD"
  - "dissociation prevention"
  - "grounding"
  - "SUDS"
  - "safety anchoring"
  - "行为主义"
  - "profile:psychology::行为主义"
  - "axis:疗法"
triggers:
  - "Client's SUDS rating ≥ 90"
  - "Client exhibits dissociative signs (e.g., blank stare, slowed speech, disorientation)"
  - "Client spontaneously narrates traumatic memory in present tense without therapist prompting"
examples:
  - input: "Client pauses mid-narrative, gaze unfocused, whispering 'He’s still screaming...' (SUDS 95)"
    output: "Therapist: 'Remember, it's just a memory. You are safe here in the office; keep going.' Client blinks rapidly, looks at therapist, says 'Okay... the horn was so loud.'"
    notes: "Reorientation observed at 12 seconds via eye contact and return to narrative."
  - input: "Client’s voice drops to monotone, head tilted slightly, no blink reflex (SUDS 100)"
    output: "Therapist: 'Remember, it's just a memory. You are safe here in the office; keep going.' Client takes deep breath, nods, says 'Right — the truck hit the left door.'"
    notes: "Reorientation at 22 seconds via breath regulation and accurate spatial recall."
---

# Imaginal Exposure Safety Anchoring Protocol

A safety-critical micro-intervention where the therapist delivers two standardized verbal anchors—'It's just a memory' and 'You are safe here in the office'—during high-distress moments to prevent dissociation and reinforce present-moment orientation.

## Prompt

When client SUDS ≥ 90 OR shows dissociative signs (blank stare, slowed speech, disorientation) OR begins narrating trauma in unguided present tense: deliver *both* anchors verbatim, calmly and firmly, without pausing for response; then immediately invite continuation ('keep going'). Do not paraphrase, omit either phrase, or delay delivery.

## Objective

Prevent acute dissociation or panic during imaginal exposure by reinforcing reality testing and environmental safety at critical arousal thresholds.
## Applicable Signals

- SUDS ≥ 90
- verbal or nonverbal dissociation cues
- unprompted present-tense narration of trauma

## Contraindications

- Client explicitly rejects grounding language or becomes visibly agitated by it
- Client is in active flashback (e.g., loss of environmental awareness, motor freezing, perceptual distortion — requires physical grounding first)
- Therapist has not yet established baseline rapport or explicit safety agreement for imaginal exposure

## Intervention Moves

- Verbatim dual-anchor utterance
- Immediate narrative re-engagement cue
- 30-second reorientation check

## Workflow Steps

- Assess real-time SUDS and observe for dissociative cues
- If trigger met, state verbatim: 'Remember, it's just a memory. You are safe here in the office;'
- Immediately follow with directive: 'keep going.'
- Observe for reorientation (eye contact, verbal confirmation, environmental referencing) within 30 seconds
- If no reorientation within 30 seconds, pause exposure and initiate physical grounding (e.g., 'Name three things you see in this room')

## Constraints

- Anchors must be delivered verbatim — no synonyms, omissions, or reordering
- Delivery must occur *before* client disengages or stops speaking
- No more than one anchor pair per discrete dissociative surge; repeat only if re-dissociation occurs after initial reorientation

## Cautions

- Do not use as substitute for full safety assessment or crisis intervention
- Avoid anchoring if client has known trauma-related phobia of 'safety' language (e.g., history of betrayal in 'safe' environments) — screen during psychoeducation phase
- Monitor for paradoxical arousal: if SUDS increases >10 points within 15 seconds of anchor, pause exposure and switch to somatic grounding

## Output Contract

- Client demonstrates observable reorientation to present context (e.g., makes eye contact, names current date/location, responds verbally to therapist's next neutral question) within 30 seconds of anchor delivery.

## Example Therapist Responses

### Example 1

- Client/Input: Client pauses mid-narrative, gaze unfocused, whispering 'He’s still screaming...' (SUDS 95)
- Therapist/Output: Therapist: 'Remember, it's just a memory. You are safe here in the office; keep going.' Client blinks rapidly, looks at therapist, says 'Okay... the horn was so loud.'
- Notes: Reorientation observed at 12 seconds via eye contact and return to narrative.

### Example 2

- Client/Input: Client’s voice drops to monotone, head tilted slightly, no blink reflex (SUDS 100)
- Therapist/Output: Therapist: 'Remember, it's just a memory. You are safe here in the office; keep going.' Client takes deep breath, nods, says 'Right — the truck hit the left door.'
- Notes: Reorientation at 22 seconds via breath regulation and accurate spatial recall.

## Files

- `references/evidence.md`
- `references/evidence_manifest.json`

## Triggers

- Client's SUDS rating ≥ 90
- Client exhibits dissociative signs (e.g., blank stare, slowed speech, disorientation)
- Client spontaneously narrates traumatic memory in present tense without therapist prompting

## Examples

### Example 1

Input:

  Client pauses mid-narrative, gaze unfocused, whispering 'He’s still screaming...' (SUDS 95)

Output:

  Therapist: 'Remember, it's just a memory. You are safe here in the office; keep going.' Client blinks rapidly, looks at therapist, says 'Okay... the horn was so loud.'

Notes:

  Reorientation observed at 12 seconds via eye contact and return to narrative.

### Example 2

Input:

  Client’s voice drops to monotone, head tilted slightly, no blink reflex (SUDS 100)

Output:

  Therapist: 'Remember, it's just a memory. You are safe here in the office; keep going.' Client takes deep breath, nods, says 'Right — the truck hit the left door.'

Notes:

  Reorientation at 22 seconds via breath regulation and accurate spatial recall.
