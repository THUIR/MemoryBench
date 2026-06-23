---
id: "cd237a75-d3c5-5263-926b-4c667a6c1ee4"
name: "心理咨询"
description: "心理咨询 的领域总导航技能：负责进入对应 family 的总路由。"
version: "0.1.0"
tags:
  - "心理咨询"
  - "kind:domain_root"
  - "profile:psychology::后现代主义"
  - "axis:疗法"
triggers:
  - "心理咨询"
  - "心理咨询 总导航"
---

# 心理咨询

心理咨询 的领域总导航技能：负责进入对应 family 的总路由。

## Prompt

## Family目录
- [人本-存在主义](心理咨询/Family技能/人本-存在主义/总技能/SKILL.md) ｜ 已同步技能数：6
- [后现代主义](心理咨询/Family技能/后现代主义/总技能/SKILL.md) ｜ 已同步技能数：9
- [心理动力学](心理咨询/Family技能/心理动力学/总技能/SKILL.md) ｜ 已同步技能数：17
- [行为主义](心理咨询/Family技能/行为主义/总技能/SKILL.md) ｜ 已同步技能数：11
- [认知行为疗法](心理咨询/Family技能/认知行为疗法/总技能/SKILL.md) ｜ 已同步技能数：68

## 选用规则（各 Family）
- 优先根据文档中明确的方法学术语、章节主题和任务目标进入对应 family。
- 当同一文档未显式指定 family 时，AutoSkill4Doc 会在配置的 family_candidates 中做受约束分类。
- 进入 family 后，再由 family 总技能继续选择一级、二级和微技能。

## 输出格式
- domain_route:
  - domain: 心理咨询
  - family: 选中的 family 名称
  - rationale: 说明为什么选择该 family

## Files

- `references/domain_manifest.json`

## Triggers

- 心理咨询
- 心理咨询 总导航
