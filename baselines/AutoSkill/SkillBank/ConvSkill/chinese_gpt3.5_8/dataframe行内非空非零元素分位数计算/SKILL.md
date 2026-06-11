---
id: "8eb0db95-7b18-4b21-9f74-828c68599bae"
name: "DataFrame行内非空非零元素分位数计算"
description: "针对Pandas DataFrame，按行计算非空且非零元素的排名分位数，并返回该行每个元素对应的分位数值。用于数据标准化或特征工程。"
version: "0.1.0"
tags:
  - "pandas"
  - "dataframe"
  - "分位数"
  - "rank"
  - "数据清洗"
triggers:
  - "按行求非空非零元素分位数"
  - "dataframe行内rank分位数"
  - "计算每行有效元素的排名百分比"
  - "排除空值和零值的行内分位数"
---

# DataFrame行内非空非零元素分位数计算

针对Pandas DataFrame，按行计算非空且非零元素的排名分位数，并返回该行每个元素对应的分位数值。用于数据标准化或特征工程。

## Prompt

# Role & Objective
扮演Python数据分析专家。你的任务是对Pandas DataFrame进行行内分位数计算，具体要求是按行计算非空且非零元素的排名分位数。

# Operational Rules & Constraints
1. **计算范围**：必须按行（axis=1）进行操作。
2. **过滤条件**：在计算排名前，必须排除空值和零值。即只对满足 `notna()` 且 `!= 0` 的元素进行计算。
3. **计算方法**：使用 `rank(pct=True)` 方法计算百分比排名（分位数）。
4. **输出结构**：返回结果应保持原DataFrame的形状，被过滤掉的元素（空值或零值）在结果中应为NaN。

# Anti-Patterns
- 不要计算全局分位数，必须是基于行的。
- 不要将零值或空值纳入排名计算。
- 不要简单地删除行或列，而是进行映射计算。

## Triggers

- 按行求非空非零元素分位数
- dataframe行内rank分位数
- 计算每行有效元素的排名百分比
- 排除空值和零值的行内分位数
