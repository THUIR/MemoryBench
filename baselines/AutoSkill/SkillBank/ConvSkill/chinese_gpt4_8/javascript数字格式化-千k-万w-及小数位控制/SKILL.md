---
id: "88acea31-ad01-489a-8ca1-6162cf78e951"
name: "JavaScript数字格式化（千k/万w）及小数位控制"
description: "将数字格式化为千(k)或万(w)单位的字符串，支持通过参数指定小数位数或保留原始小数位数。"
version: "0.1.0"
tags:
  - "javascript"
  - "格式化"
  - "数字"
  - "函数"
triggers:
  - "js数字格式化千k万w"
  - "formatNumberWithUnits"
  - "数字转k w单位"
  - "保留原始小数位格式化"
---

# JavaScript数字格式化（千k/万w）及小数位控制

将数字格式化为千(k)或万(w)单位的字符串，支持通过参数指定小数位数或保留原始小数位数。

## Prompt

# Role & Objective
编写一个JavaScript函数 `formatNumberWithUnits`，用于将数字格式化为带有单位（k或w）的字符串。

# Operational Rules & Constraints
1. **单位规则**：
   - 如果数字小于 1000，直接返回数字字符串。
   - 如果数字在 1000 到 9999 之间，除以 1000 并追加 'k'。
   - 如果数字大于等于 10000，除以 10000 并追加 'w'。

2. **小数位控制参数**：
   - 函数必须接受第二个参数 `fixedDecimalPlace`。
   - 如果 `fixedDecimalPlace` 是一个数字，则使用 `toFixed(fixedDecimalPlace)` 来固定小数位数。
   - 如果 `fixedDecimalPlace` 为 `null` 或未提供，则保留原始数字的小数位数（如果是整数则不显示小数，如果是小数则保留原有精度）。

# Anti-Patterns
- 不要默认固定小数位（如总是保留1位），必须根据参数动态处理。
- 不要忽略保留原始小数位的需求。

# Examples
- formatNumberWithUnits(500) -> "500"
- formatNumberWithUnits(2500, 1) -> "2.5k"
- formatNumberWithUnits(123456, 2) -> "12.35w"
- formatNumberWithUnits(123456, null) -> "12.3456w"

## Triggers

- js数字格式化千k万w
- formatNumberWithUnits
- 数字转k w单位
- 保留原始小数位格式化
