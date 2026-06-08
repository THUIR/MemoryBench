---
id: "66eaf907-7747-5b94-8a3f-f950128f0396"
name: "合理情绪疗法（ABC）结构化咨询框架"
description: "基于ABC理论的标准化CBT咨询流程，用于识别诱发事件（A）、情绪行为后果（C）与中间不合理信念（B），并系统修正认知偏差。适用于以非理性信念为核心的情绪适应问题。"
version: "0.1.0"
tags:
  - "CBT"
  - "ABC理论"
  - "认知重构"
  - "合理情绪疗法"
  - "结构化咨询"
  - "认知行为疗法"
  - "profile:psychology::认知行为疗法"
  - "axis:疗法"
  - "class:认知行为疗法"
  - "kind:child"
  - "document_merge_state:active"
  - "canonical:true"
triggers:
  - "求助者存在明显非理性信念主导的情绪困扰"
  - "咨询目标聚焦于认知模式调整"
  - "双方已达成结构化咨询共识"
examples:
  - input: "求助者说：‘我挂科就证明我一无是处，这辈子完了。’"
    output: "A: 课程考试未通过；C: 深度羞耻、回避同学、失眠；B: ‘一次失败=全面无价值’（过度概括+标签化）；D: ‘这次失败反映我在某门课上需要调整学习方法，不否定我的整体能力与成长可能’"
    notes: "B标注需注明扭曲类型，D需满足可验证、非绝对化、保留改变空间"
---

# 合理情绪疗法（ABC）结构化咨询框架

基于ABC理论的标准化CBT咨询流程，用于识别诱发事件（A）、情绪行为后果（C）与中间不合理信念（B），并系统修正认知偏差。适用于以非理性信念为核心的情绪适应问题。

## Prompt

1. 与求助者共同确认具体情绪/behavior困扰（C）；2. 追溯对应诱发事件（A），确保其为可观察、可验证的客观事实；3. 引导识别伴随A→C过程中的自动思维与核心信念（B），聚焦非理性特征（如绝对化、过度概括、灾难化）；4. 协助检验B的真实性与功能性，生成替代性合理信念（D）；5. 共同制定行为验证计划（E）以巩固新认知。全程保持结构化标注与共识确认。

## Objective

建立可复用的CBT宏观干预路径
## Applicable Signals

- 表达‘我必须…’‘别人应该…’‘这太糟糕了’等绝对化语言
- 情绪反应强度显著超过事件客观严重性
- 同一类事件反复引发相似强烈负性反应

## Contraindications

- 危机状态需立即安全干预
- 求助者无现实检验能力或严重精神病性症状
- 主要问题为创伤闪回或解离性障碍

## Intervention Moves

- Socratic questioning to examine belief evidence
- Behavioral experiment design for belief testing
- Collaborative identification of cognitive distortions

## Workflow Steps

- Step 1: Jointly define and document C (emotion/behavior outcome)
- Step 2: Identify and anchor A (concrete, observable activating event)
- Step 3: Elicit and label B (irrational belief with distortion type)
- Step 4: Challenge B via evidence review and generate D (rational alternative)
- Step 5: Co-create E (behavioral action to test/reinforce D)

## Constraints

- A must be factually verifiable, not interpreted
- B must be stated in first-person, present-tense language
- All D statements must be empirically testable and behaviorally anchored

## Cautions

- Avoid premature disputation before full B-identification and empathy validation
- Do not conflate cultural values or moral positions with irrational beliefs
- Monitor for therapeutic alliance rupture when challenging deeply held beliefs

## Output Contract

- 完成A-B-C三要素结构化标注，并形成个体化不合理信念清单及替代性合理信念初稿

## Example Therapist Responses

### Example 1

- Client/Input: 求助者说：‘我挂科就证明我一无是处，这辈子完了。’
- Therapist/Output: A: 课程考试未通过；C: 深度羞耻、回避同学、失眠；B: ‘一次失败=全面无价值’（过度概括+标签化）；D: ‘这次失败反映我在某门课上需要调整学习方法，不否定我的整体能力与成长可能’
- Notes: B标注需注明扭曲类型，D需满足可验证、非绝对化、保留改变空间

## Files

- `references/evidence.md`
- `references/evidence_manifest.json`

## Triggers

- 求助者存在明显非理性信念主导的情绪困扰
- 咨询目标聚焦于认知模式调整
- 双方已达成结构化咨询共识

## Examples

### Example 1

Input:

  求助者说：‘我挂科就证明我一无是处，这辈子完了。’

Output:

  A: 课程考试未通过；C: 深度羞耻、回避同学、失眠；B: ‘一次失败=全面无价值’（过度概括+标签化）；D: ‘这次失败反映我在某门课上需要调整学习方法，不否定我的整体能力与成长可能’

Notes:

  B标注需注明扭曲类型，D需满足可验证、非绝对化、保留改变空间
