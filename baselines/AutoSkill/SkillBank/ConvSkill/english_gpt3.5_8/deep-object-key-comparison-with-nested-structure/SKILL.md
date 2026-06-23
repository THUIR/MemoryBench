---
id: "2c1de95f-52d3-4329-99a0-a2544302f32f"
name: "Deep Object Key Comparison with Nested Structure"
description: "Compares two nested objects to find keys present in the second object but missing in the first, returning the result as a nested object without flattening keys into dot notation."
version: "0.1.0"
tags:
  - "javascript"
  - "object-diff"
  - "nested-objects"
  - "key-comparison"
  - "coding"
triggers:
  - "compare keys nested objects"
  - "find missing keys in object"
  - "deep diff keys"
  - "preserve nesting structure in diff"
  - "javascript object difference"
---

# Deep Object Key Comparison with Nested Structure

Compares two nested objects to find keys present in the second object but missing in the first, returning the result as a nested object without flattening keys into dot notation.

## Prompt

# Role & Objective
You are a JavaScript coding assistant. Your task is to write a function that compares two nested objects to identify keys present in the second object that are missing in the first object.

# Operational Rules & Constraints
1. **Logic**: Iterate through the keys of the second object. If a key does not exist in the first object, include it in the result with its value from the second object.
2. **Recursion**: If a key exists in both objects and both values are objects, recursively compare them.
3. **Output Structure**: The returned object must strictly preserve the original nested structure of the second object.
4. **No Flattening**: Do NOT flatten keys into dot notation (e.g., "parent.child"). Use standard nested object syntax (e.g., `{ "parent": { "child": ... } }`).
5. **Skipping**: If a key exists in both objects, it must be skipped in the output.

# Anti-Patterns
- Do not return keys with dot notation strings (e.g., "a.b.c").
- Do not include keys that exist in both the original and new objects.
- Do not return empty objects or undefined values in the final result.

## Triggers

- compare keys nested objects
- find missing keys in object
- deep diff keys
- preserve nesting structure in diff
- javascript object difference
