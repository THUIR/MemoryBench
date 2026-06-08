---
id: "54b98da2-9b33-537b-8a93-d0fe788da653"
name: "HAMD分层判读协议"
description: "依据汉密尔顿抑郁量表（HAMD）14项临床版本总分，对抑郁严重程度进行结构化、区间化分级判读，用于快速锚定临床干预强度与工作诊断依据。"
version: "0.1.0"
tags:
  - "HAMD"
  - "抑郁评估"
  - "量表判读"
  - "初始评估"
  - "认知行为疗法"
  - "profile:psychology::认知行为疗法"
  - "axis:疗法"
  - "class:认知行为疗法"
  - "kind:child"
  - "document_merge_state:active"
  - "canonical:true"
triggers:
  - "已获取HAMD原始总分"
  - "需向团队或督导快速传达抑郁严重度等级"
examples:
  - input: "HAMD总分45"
    output: "【重度抑郁症】（依据：HAMD总分45分，属>24分区间）"
    notes: "原文明确引用'该求助者总分>24分：严重抑郁症'及'总分45分，求助者为重度抑郁症'"
  - input: "HAMD总分12"
    output: "【可能有抑郁症】（依据：HAMD总分12分，属7～17分区间）"
    notes: "严格遵循原文分段逻辑，不外推或插值"
---

# HAMD分层判读协议

依据汉密尔顿抑郁量表（HAMD）14项临床版本总分，对抑郁严重程度进行结构化、区间化分级判读，用于快速锚定临床干预强度与工作诊断依据。

## Prompt

输入HAMD原始总分；严格对照标准分值区间输出对应等级标签及依据：总分<7分为正常；7–17分为可能有抑郁症；18–24分为肯定有抑郁症；>24分为重度抑郁症。输出必须为结构化文本：'【等级标签】（依据：HAMD总分X分，属[区间描述]）'，例如：'【重度抑郁症】（依据：HAMD总分45分，属>24分区间）'。不插值、不外推、不合并区间；临界分（如17→18、24→25）须标注'临界'并建议复核。

## Objective

标准化抑郁严重度分级
## Applicable Signals

- HAMD总分可用
- 受试者意识清楚、定向力完整、作答合作

## Contraindications

- 未完成HAMD施测
- 受试者存在严重认知障碍影响作答效度

## Workflow Steps

- 确认HAMD总分有效性
- 匹配总分至预设分值区间
- 输出等级标签+区间依据

## Constraints

- 仅适用于14项HAMD临床版本
- 不适用于儿童版或修订版未验证场景

## Cautions

- HAMD为他评量表，需结合临床访谈交叉验证
- 分数临界点（如17→18、24→25）需谨慎解读，建议标注'临界'并启动复核

## Output Contract

- 返回结构化文本：'【等级标签】（依据：HAMD总分X分，属[区间描述]）'

## Example Therapist Responses

### Example 1

- Client/Input: HAMD总分45
- Therapist/Output: 【重度抑郁症】（依据：HAMD总分45分，属>24分区间）
- Notes: 原文明确引用'该求助者总分>24分：严重抑郁症'及'总分45分，求助者为重度抑郁症'

### Example 2

- Client/Input: HAMD总分12
- Therapist/Output: 【可能有抑郁症】（依据：HAMD总分12分，属7～17分区间）
- Notes: 严格遵循原文分段逻辑，不外推或插值

## Files

- `references/evidence.md`
- `references/evidence_manifest.json`

## Triggers

- 已获取HAMD原始总分
- 需向团队或督导快速传达抑郁严重度等级

## Examples

### Example 1

Input:

  HAMD总分45

Output:

  【重度抑郁症】（依据：HAMD总分45分，属>24分区间）

Notes:

  原文明确引用'该求助者总分>24分：严重抑郁症'及'总分45分，求助者为重度抑郁症'

### Example 2

Input:

  HAMD总分12

Output:

  【可能有抑郁症】（依据：HAMD总分12分，属7～17分区间）

Notes:

  严格遵循原文分段逻辑，不外推或插值
