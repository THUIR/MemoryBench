---
id: "c7c07c2f-240a-5b3a-85d1-78fdd90bf17d"
name: "资源确认性澄清"
description: "运用确认+澄清技术，帮助来访者区分‘自杀意愿’与‘对解脱的渴望’，将自杀重构为一次失败的问题解决尝试而非终极目标，从而为探索替代方案腾出心理空间。"
version: "0.1.0"
tags:
  - "suicide_prevention"
  - "humanistic"
  - "existential"
  - "resource_oriented"
  - "crisis_engagement"
  - "人本-存在主义"
  - "profile:psychology::人本_存在主义"
  - "axis:疗法"
triggers:
  - "Client states 'I want to die' without elaboration"
  - "Client links suicide to overwhelming emotion rather than hopelessness or worthlessness"
  - "Client shows openness to reflection (e.g., pauses, sighs, softens tone)"
examples:
  - input: "我觉得活着好累，不如死了算了。"
    output: "‘这累，是压得你连呼吸都想停下来的那种累吧？……你真正想摆脱的，是不是这种一刻都不能再撑下去的感觉？其实你之前已经试过让自己安全一点——比如去图书馆——那说明你心里一直有在找出口。’"
  - input: "我真想一了百了。"
    output: "‘那一了百了的背后，是不是特别特别想让这种撕裂感彻底停下来？……你愿意说这些，本身就说明你还没放弃寻找别的可能。’"
---

# 资源确认性澄清

运用确认+澄清技术，帮助来访者区分‘自杀意愿’与‘对解脱的渴望’，将自杀重构为一次失败的问题解决尝试而非终极目标，从而为探索替代方案腾出心理空间。

## Prompt

当来访者表达‘我想死’类陈述时，先以共情性确认承接其情绪强度（如：‘这感觉真的太重了，压得你喘不过气’），再温和澄清动机本质（如：‘你真正想要的，是不是那种终于不再被痛苦淹没的感觉？’），最后锚定其内在能动性（如：‘你已经试过一些方法——比如去人多的地方——说明你一直在努力找出口’）。全程避免解释、纠正或建议，仅通过语调、停顿和精准措辞引导来访者自我觉察。

## Objective

Shift client’s self-attribution from pathological intent to understandable distress response, enabling agency and alternatives.
## Applicable Signals

- Verbal expression of suicidal ideation without plan/intent
- Affective overwhelm without flat affect or psychomotor retardation
- Momentary softening, eye contact shift, or verbal hesitation after initial statement

## Contraindications

- Client is actively planning or rehearsing means
- Client rejects therapist's empathic framing as invalidating
- Client is minimally verbal or dissociated

## Intervention Moves

- confirming
- clarifying
- reframing_as_attempt
- agency_anchoring

## Workflow Steps

- 1. Confirm emotional reality: name the intensity and legitimacy of the felt burden.
- 2. Clarify motivational structure: distinguish desire for cessation of suffering from desire for self-annihilation.
- 3. Anchor agency: reference past adaptive efforts (e.g., seeking safety, reaching out) as evidence of problem-solving capacity.
- 4. Pause and invite co-reflection: ‘What would it feel like if that relief came another way?’

## Constraints

- Must occur only after safety assessment confirms no imminent risk
- Requires prior establishment of therapeutic alliance (e.g., at least one session with consistent attunement)
- Therapist must avoid any language implying judgment, minimization, or premature solution-giving

## Cautions

- Do not use if client’s narrative centers chronic hopelessness or identity-level worthlessness — this intervention presumes distress is situational and solvable
- Avoid metaphors that pathologize (e.g., ‘you’re not thinking clearly’) or over-interpret (e.g., ‘what you really mean is…’)

## Output Contract

- Client articulates variation of: 'I don’t really want to die — I just can’t bear this feeling right now, and I haven’t found another way out.'

## Example Therapist Responses

### Example 1

- Client/Input: 我觉得活着好累，不如死了算了。
- Therapist/Output: ‘这累，是压得你连呼吸都想停下来的那种累吧？……你真正想摆脱的，是不是这种一刻都不能再撑下去的感觉？其实你之前已经试过让自己安全一点——比如去图书馆——那说明你心里一直有在找出口。’

### Example 2

- Client/Input: 我真想一了百了。
- Therapist/Output: ‘那一了百了的背后，是不是特别特别想让这种撕裂感彻底停下来？……你愿意说这些，本身就说明你还没放弃寻找别的可能。’

## Files

- `references/evidence.md`
- `references/evidence_manifest.json`

## Triggers

- Client states 'I want to die' without elaboration
- Client links suicide to overwhelming emotion rather than hopelessness or worthlessness
- Client shows openness to reflection (e.g., pauses, sighs, softens tone)

## Examples

### Example 1

Input:

  我觉得活着好累，不如死了算了。

Output:

  ‘这累，是压得你连呼吸都想停下来的那种累吧？……你真正想摆脱的，是不是这种一刻都不能再撑下去的感觉？其实你之前已经试过让自己安全一点——比如去图书馆——那说明你心里一直有在找出口。’

### Example 2

Input:

  我真想一了百了。

Output:

  ‘那一了百了的背后，是不是特别特别想让这种撕裂感彻底停下来？……你愿意说这些，本身就说明你还没放弃寻找别的可能。’
