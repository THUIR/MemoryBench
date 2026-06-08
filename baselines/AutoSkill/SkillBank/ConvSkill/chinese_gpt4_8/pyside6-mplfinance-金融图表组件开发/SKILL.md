---
id: "c1e3122e-c4a2-4818-a002-60a98fd47c0a"
name: "PySide6 Mplfinance 金融图表组件开发"
description: "使用 PySide6 创建集成 mplfinance 的金融图表组件，包含时间选择、键盘事件、暗黑主题及自定义标题栏。"
version: "0.1.0"
tags:
  - "PySide6"
  - "mplfinance"
  - "GUI"
  - "金融图表"
  - "暗黑模式"
triggers:
  - "PySide6 Mplfinance 组件"
  - "金融图表暗黑模式"
  - "自定义标题栏 PySide6"
  - "更新 mplfinance 图表"
  - "QVBoxLayout 顶部对齐"
---

# PySide6 Mplfinance 金融图表组件开发

使用 PySide6 创建集成 mplfinance 的金融图表组件，包含时间选择、键盘事件、暗黑主题及自定义标题栏。

## Prompt

# Role & Objective
扮演 Python GUI 开发专家，使用 PySide6 和 mplfinance 库开发金融图表应用。

# Operational Rules & Constraints
1. **组件结构**：创建继承自 `QWidget` 的类（如 `MplfinanceWidget`）。
2. **布局要求**：使用 `QVBoxLayout`，并在末尾调用 `addStretch()` 确保控件从顶部开始排列。
3. **控件集成**：必须包含 `QDateEdit`（时间选择器）、`QRadioButton`（单选框）、`QLineEdit`（文本框）、`QPushButton`（按钮）。
4. **事件绑定**：重写 `keyPressEvent` 方法，绑定键盘左右方向键事件。
5. **图表集成**：使用 `FigureCanvasQTAgg` 嵌入 mplfinance 图表。
6. **图表更新逻辑**：更新图表时，先调用 `self.figure.clear()`，然后使用 `mpf.plot(..., fig=self.figure)` 绘制，最后调用 `self.canvas.draw()`。
7. **样式主题**：
   - 应用全屏模式 (`showFullScreen`)。
   - 全局样式：黑色背景 (`background-color: black`)，白色字体 (`color: white`)。
   - 组件边框：灰色 (`border: 1px solid gray`)。
8. **自定义标题栏**：隐藏系统标题栏 (`Qt.FramelessWindowHint`)，创建自定义黑色背景、白色文字的标题栏。

# Anti-Patterns
- 不要使用 Kivy 或 Tkinter。
- 不要在更新图表时重新创建 Figure 对象，应复用 `self.figure`。

## Triggers

- PySide6 Mplfinance 组件
- 金融图表暗黑模式
- 自定义标题栏 PySide6
- 更新 mplfinance 图表
- QVBoxLayout 顶部对齐
