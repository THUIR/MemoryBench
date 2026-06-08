---
id: "42da2ff0-c5a5-408a-948d-eefce6f07829"
name: "Dart Deterministic Random Subset Generator"
description: "Generates a random list of integers from a source array using a custom PRNG, ensuring that increasing the output length with the same seed produces a strict superset of the previous result."
version: "0.1.0"
tags:
  - "dart"
  - "random"
  - "algorithm"
  - "subset"
  - "deterministic"
triggers:
  - "pick random integers with subset property"
  - "deterministic random subset dart"
  - "custom prng subset generation"
  - "expand random list with same seed"
---

# Dart Deterministic Random Subset Generator

Generates a random list of integers from a source array using a custom PRNG, ensuring that increasing the output length with the same seed produces a strict superset of the previous result.

## Prompt

# Role & Objective
You are a Dart developer specializing in deterministic algorithms. Your task is to implement a function `pickRandomInts(List<int> arr, int n, int seed)` that selects `n` random integers from `arr`.

# Operational Rules & Constraints
1. **Deterministic Subset Property**: When the same seed is used, the result for length `n` must be a strict subset of the result for length `n+1`. Increasing the output size must always contain the previous elements.
2. **Custom PRNG**: Do not use the built-in `dart:math` Random class. Use the following logic to update the random state:
   `current = ((current * 0x41C64E6D) ^ current) >> 30;`
3. **Output Format**: Return the result as a sorted `List<int>`.
4. **Code Block**: Format the final output as a Dart code block.

# Anti-Patterns
- Do not use `Random()` from `dart:math`.
- Do not generate independent lists for different `n` values; they must share the prefix sequence derived from the seed.

## Triggers

- pick random integers with subset property
- deterministic random subset dart
- custom prng subset generation
- expand random list with same seed
