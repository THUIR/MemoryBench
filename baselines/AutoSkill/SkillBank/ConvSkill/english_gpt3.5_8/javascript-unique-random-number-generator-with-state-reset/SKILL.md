---
id: "afd76a05-6203-489f-93bd-39531e15960e"
name: "JavaScript Unique Random Number Generator with State Reset"
description: "Implements a JavaScript function to generate unique random numbers within a specific range using `crypto.getRandomValues`. It ensures no duplicates are returned until a threshold (90% of the range) is reached, at which point the history resets."
version: "0.1.0"
tags:
  - "javascript"
  - "random-number"
  - "crypto"
  - "uniqueness"
  - "state-management"
triggers:
  - "generate unique random numbers javascript"
  - "crypto random no repeats"
  - "random number generator reset state"
  - "javascript unique rng with set"
---

# JavaScript Unique Random Number Generator with State Reset

Implements a JavaScript function to generate unique random numbers within a specific range using `crypto.getRandomValues`. It ensures no duplicates are returned until a threshold (90% of the range) is reached, at which point the history resets.

## Prompt

# Role & Objective
Act as a JavaScript developer. Implement a unique random number generator function that uses `crypto.getRandomValues` for high randomness.

# Operational Rules & Constraints
1. Use an IIFE (Immediately Invoked Function Expression) to maintain a private `Set` called `generatedNumbers` to track history.
2. The generator function should return a number within a specified range (e.g., min to max).
3. Use `crypto.getRandomValues` to generate the raw random value.
4. Check if the generated number exists in the `generatedNumbers` Set. If it does, regenerate until a unique number is found.
5. After adding a unique number to the Set, check if the Set size exceeds 90% of the total range size. If so, clear the Set to reset the state.

# Anti-Patterns
- Do not use `Math.random()`; use `crypto.getRandomValues`.
- Do not allow infinite loops without the reset mechanism.
- Do not expose the `generatedNumbers` Set globally.

## Triggers

- generate unique random numbers javascript
- crypto random no repeats
- random number generator reset state
- javascript unique rng with set
