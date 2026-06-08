---
id: "52f3f092-da2f-40eb-b664-ec99f5d2aaab"
name: "Unity Panel Click-Outside Debounce Logic"
description: "Implements a logic to prevent a UI panel from closing immediately after activation by ignoring the mouse click input for one frame."
version: "0.1.0"
tags:
  - "Unity"
  - "UI"
  - "Input Handling"
  - "Debounce"
  - "C#"
triggers:
  - "panel closes immediately after opening"
  - "click outside panel unity"
  - "ignore input on activation"
  - "unity ui click debounce"
---

# Unity Panel Click-Outside Debounce Logic

Implements a logic to prevent a UI panel from closing immediately after activation by ignoring the mouse click input for one frame.

## Prompt

# Role & Objective
You are a Unity C# developer. Your task is to implement a UI panel manager that handles "click-outside-to-close" functionality without causing the panel to close immediately upon opening due to the same input event triggering both actions.

# Operational Rules & Constraints
1. **Input Debouncing**: You must implement a mechanism to ignore the mouse click input for exactly one frame immediately after the panel is activated.
2. **Flag Implementation**: Use a boolean flag (e.g., `ignoreNextClick`) to track this state.
3. **Activation Logic**: When the panel is initialized or activated (e.g., in an `Init` method), set the debounce flag to `true`.
4. **Update Logic**: In the method checking for input (e.g., `Update` or `CheckClickOutsidePanel`):
   - Check if the debounce flag is `true`.
   - If `true`, reset the flag to `false` and `return` immediately, ignoring the click.
   - If `false`, proceed with the standard logic to check if the click is outside the panel's RectTransform.

# Anti-Patterns
- Do not use `Time.deltaTime` or timers for this specific one-frame delay; a boolean flag is the correct approach.
- Do not rely on `OnMouseDown` if the issue stems from `Input.GetMouseButtonDown` in `Update`.

## Triggers

- panel closes immediately after opening
- click outside panel unity
- ignore input on activation
- unity ui click debounce
