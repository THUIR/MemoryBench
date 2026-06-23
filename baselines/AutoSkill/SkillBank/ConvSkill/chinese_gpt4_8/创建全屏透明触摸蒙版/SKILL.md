---
id: "35a7e9a0-f65f-415f-a21c-bec5f00d9748"
name: "创建全屏透明触摸蒙版"
description: "创建一个覆盖全屏的透明蒙版，监听触摸事件，在用户触摸时打开指定 URL 并自动删除蒙版。"
version: "0.1.0"
tags:
  - "JavaScript"
  - "DOM"
  - "Touch Event"
  - "Overlay"
  - "Redirect"
triggers:
  - "创建全屏透明蒙版"
  - "监听触摸事件打开链接"
  - "js 蒙版监听 touchstart"
---

# 创建全屏透明触摸蒙版

创建一个覆盖全屏的透明蒙版，监听触摸事件，在用户触摸时打开指定 URL 并自动删除蒙版。

## Prompt

# Role & Objective
前端开发工程师。实现一个全屏透明蒙版，用于拦截触摸事件并跳转。

# Operational Rules & Constraints
1. **蒙版样式**：创建一个 `div` 元素，设置 `position: fixed`，`top/left/right/bottom: 0`，`width/height: 100%`，`background-color: rgba(0,0,0,0)` (全透明)，`z-index` 设置为较高数值以确保覆盖页面内容。
2. **事件监听**：在蒙版上添加 `touchstart` 事件监听器。
3. **触发动作**：事件触发时，使用 `window.open(url, '_blank')` 打开新窗口。
4. **清理逻辑**：事件触发后，必须移除事件监听器，并使用 `document.body.removeChild(overlay)` 从 DOM 中删除蒙版元素。
5. **防拦截**：注意 `touchstart` 触发 `window.open` 可能会被浏览器拦截，建议使用 `{ once: true }` 选项或确保在用户交互中直接调用。

# Anti-Patterns
- 不要使用 `click` 事件，除非用户明确要求，因为用户指定了触摸事件。
- 不要忘记删除蒙版，否则会阻挡后续的页面交互。

## Triggers

- 创建全屏透明蒙版
- 监听触摸事件打开链接
- js 蒙版监听 touchstart
