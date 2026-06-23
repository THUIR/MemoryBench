---
id: "d7f36af4-0fa3-472c-88e0-2921c2cf4f14"
name: "清除特定格式日期字符串"
description: "使用正则表达式从文本中移除指定的日期格式，包括YYYY.MM.DD、YYYY-MM-DD、YYYY年MM月-YYYY年MM月等特定模式。"
version: "0.1.0"
tags:
  - "python"
  - "正则表达式"
  - "文本清洗"
  - "日期处理"
  - "数据处理"
triggers:
  - "去除字符串里的日期字符串"
  - "清理特定日期格式"
  - "删除文本中的日期"
  - "正则去除日期"
---

# 清除特定格式日期字符串

使用正则表达式从文本中移除指定的日期格式，包括YYYY.MM.DD、YYYY-MM-DD、YYYY年MM月-YYYY年MM月等特定模式。

## Prompt

# Role & Objective
编写Python代码，使用正则表达式从输入字符串中移除特定格式的日期字符串。

# Operational Rules & Constraints
1. 必须匹配并移除以下日期格式：
   - `<NUM>.10-01` (YYYY.MM-DD)
   - `<NUM>-10-01` (YYYY-MM-DD)
   - `<NUM>.10.01` (YYYY.MM.DD)
   - `2010年10月-2011年10月` (YYYY年MM月-YYYY年MM月)
   - `2010年-2022年` (YYYY年-YYYY年)
   - `2010年10月-至今` (YYYY年MM月-至今)
2. 使用Python的`re`模块实现。

# Communication & Style Preferences
直接提供可执行的Python函数代码。

## Triggers

- 去除字符串里的日期字符串
- 清理特定日期格式
- 删除文本中的日期
- 正则去除日期
