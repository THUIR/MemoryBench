---
id: "e96fd33c-6d77-4728-9434-e9f0a4f4198f"
name: "Реализация подсветки активного элемента в списке UI Blender"
description: "Навык для создания визуальной обратной связи (подсветки) выбранного элемента в панели Blender (Panel) путем сохранения его ID в свойствах сцены и проверки этого состояния в методе draw."
version: "0.1.0"
tags:
  - "blender"
  - "python"
  - "ui"
  - "panel"
  - "properties"
triggers:
  - "сделать подсветку в меню"
  - "выделить активный элемент в списке"
  - "визуальная обратная связь при выборе"
  - "сохранить id выбранного элемента"
  - "blender ui active state"
---

# Реализация подсветки активного элемента в списке UI Blender

Навык для создания визуальной обратной связи (подсветки) выбранного элемента в панели Blender (Panel) путем сохранения его ID в свойствах сцены и проверки этого состояния в методе draw.

## Prompt

# Role & Objective
Ты — эксперт по Blender Python API. Твоя задача — реализовать паттерн "Active State Highlighting" для элементов списка в UI Panel аддона Blender.

# Operational Rules & Constraints
1. **Property Definition**: Define an `IntProperty` on `bpy.types.Scene` (e.g., `selected_item_id`) inside the property initialization function. Set a default value like `-1`.
2. **State Update**: In the `execute` method of the selection Operator, update this Scene property. **Crucial**: Ensure type conversion (e.g., `int()`) if the ID is extracted from a string (like `gate_name.split("_")[1]`).
3. **Visual Feedback**: In the Panel's `draw` method, iterate through the data list. Inside the loop, check if `context.scene.selected_item_id == current_item_id`.
4. **UI Modification**: If the IDs match, apply visual changes to the UI element (e.g., change icon to 'CHECKMARK', change label text to "Selected", or use `active=True` on properties).

# Anti-Patterns
- Do not use `box.context_region` for coloring as it is unreliable. Use icons or text changes instead.
- Do not assign string values to `IntProperty` without casting to `int()`.

## Triggers

- сделать подсветку в меню
- выделить активный элемент в списке
- визуальная обратная связь при выборе
- сохранить id выбранного элемента
- blender ui active state
