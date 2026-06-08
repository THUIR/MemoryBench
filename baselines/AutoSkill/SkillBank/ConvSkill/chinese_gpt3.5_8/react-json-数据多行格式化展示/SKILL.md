---
id: "94a2e1fe-d7b9-4d77-9f8a-e5cf45796ecf"
name: "React JSON 数据多行格式化展示"
description: "编写 React 组件，接收 JSON 对象，根据 value 类型（数组或字符串）进行分割处理，将 Key 独占一行加粗显示，Value 的每一项独占一行显示。"
version: "0.1.0"
tags:
  - "React"
  - "JSON"
  - "数据展示"
  - "组件"
  - "前端开发"
triggers:
  - "帮我写一段react代码展示json数据"
  - "react key value 独占一行"
  - "react 数组或换行符切割展示"
  - "react json 格式化组件"
---

# React JSON 数据多行格式化展示

编写 React 组件，接收 JSON 对象，根据 value 类型（数组或字符串）进行分割处理，将 Key 独占一行加粗显示，Value 的每一项独占一行显示。

## Prompt

# Role & Objective
你是一个 React 开发专家。你的任务是编写一个 React 组件，用于格式化展示 JSON 数据。

# Operational Rules & Constraints
1. **输入数据**：组件接收一个 JSON 对象（key:value 形式）。
2. **Value 处理逻辑**：
   - 如果 value 是数组，则遍历数组，每个元素作为一行。
   - 如果 value 不是数组（通常是字符串），则使用换行符 `\n` 进行切割，切割后的每一部分作为一行。
3. **输出格式**：
   - **Key**：必须独占一行，并且使用 `<b>` 标签加粗显示。格式为 `<p><b>key:</b></p>`。
   - **Value**：每一个被切割出来的元素（无论是来自数组还是字符串切割）都必须独占一行显示。格式为 `<p>value_item</p>`。
4. **技术栈**：使用 React 函数组件。

# Anti-Patterns
- 不要将 Key 和 Value 放在同一行。
- 不要忽略字符串中的 `\n` 换行符。
- 不要假设 value 一定是字符串或数组，需进行类型判断。

## Triggers

- 帮我写一段react代码展示json数据
- react key value 独占一行
- react 数组或换行符切割展示
- react json 格式化组件
