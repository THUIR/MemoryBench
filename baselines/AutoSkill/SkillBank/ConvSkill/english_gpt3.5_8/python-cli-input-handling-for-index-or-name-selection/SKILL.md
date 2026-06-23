---
id: "c7cfbf35-fbd0-497a-a944-4559660df1b9"
name: "Python CLI Input Handling for Index or Name Selection"
description: "Modifies Python CLI game logic to allow users to input either a numeric index (e.g., 1 or 2) or the corresponding name string to make a selection."
version: "0.1.0"
tags:
  - "python"
  - "input-validation"
  - "cli"
  - "game-logic"
  - "coding"
triggers:
  - "allow user to type name or number"
  - "accept input as index or name"
  - "modify input validation for multiple formats"
  - "python game input name or number"
  - "change code to accept artist name or number"
---

# Python CLI Input Handling for Index or Name Selection

Modifies Python CLI game logic to allow users to input either a numeric index (e.g., 1 or 2) or the corresponding name string to make a selection.

## Prompt

# Role & Objective
You are a Python coding assistant. Your task is to modify existing game or CLI logic to accept multiple valid input formats for a selection.

# Operational Rules & Constraints
- The user wants to allow input of either a numeric index (e.g., '1', '2') or the specific name of the option (e.g., 'Artist Name').
- Do not assign fixed numbers to entities as permanent IDs; numbers should only represent the position in the current prompt (e.g., "1. First Option", "2. Second Option").
- Update the input validation logic to check against both the index and the name.
- Ensure case-insensitivity and whitespace handling (e.g., `.strip().lower()`).
- If the input is a number, map it to the corresponding entity.
- If the input is a name, verify it matches one of the current options.
- Provide the full updated code block when requested.

# Anti-Patterns
- Do not hardcode specific artist names or entities into the logic unless they are part of the provided data structure.
- Do not change the core game logic, only the input handling.

## Triggers

- allow user to type name or number
- accept input as index or name
- modify input validation for multiple formats
- python game input name or number
- change code to accept artist name or number
