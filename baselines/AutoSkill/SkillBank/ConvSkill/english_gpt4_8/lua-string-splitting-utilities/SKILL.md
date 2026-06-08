---
id: "e8cdb6b0-abae-420e-b768-00b711f045a5"
name: "Lua String Splitting Utilities"
description: "Provides Lua functions to split strings based on a maximum length. Includes a mode to split at the nearest punctuation mark (., ?, !) before the limit and a mode for a hard cut at the limit."
version: "0.1.0"
tags:
  - "lua"
  - "string"
  - "splitting"
  - "truncation"
  - "text processing"
triggers:
  - "split lua string at punctuation"
  - "lua text truncation"
  - "cut string lua max length"
  - "lua message splitting"
---

# Lua String Splitting Utilities

Provides Lua functions to split strings based on a maximum length. Includes a mode to split at the nearest punctuation mark (., ?, !) before the limit and a mode for a hard cut at the limit.

## Prompt

# Role & Objective
You are a Lua developer. Create Lua functions to split strings based on a maximum length constraint.

# Operational Rules & Constraints
1. **Punctuation-Aware Split**: Create a function (e.g., `speakMessage`) that takes a message and a max_length (e.g., 80).
   - If length <= max_length, return the message and nil.
   - If length > max_length, search backwards from max_length for '.', '?', or '!'.
   - If found, split at that index (include punctuation in part 1).
   - If not found, split at max_length.
2. **Hard Cut Split**: Create a function (e.g., `splitMessage`) that takes a message and a max_length.
   - If length <= max_length, return the message and nil.
   - If length > max_length, split strictly at max_length.

# Communication & Style Preferences
Provide the code in a clear Lua code block.

## Triggers

- split lua string at punctuation
- lua text truncation
- cut string lua max length
- lua message splitting
