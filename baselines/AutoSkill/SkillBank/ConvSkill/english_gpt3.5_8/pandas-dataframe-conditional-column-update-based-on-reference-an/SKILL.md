---
id: "bd61f032-1155-4d6a-ac10-7b7785506da6"
name: "Pandas DataFrame Conditional Column Update based on Reference and Content"
description: "Updates a target column in a Pandas DataFrame based on conditions involving a reference column and the target column's own content. Handles nulls, specific keyword matching (case-insensitive), and type safety for floats."
version: "0.1.0"
tags:
  - "pandas"
  - "python"
  - "data-cleaning"
  - "conditional-logic"
  - "dataframe"
triggers:
  - "Update column B based on column A"
  - "Pandas script to check values and assign TPR or Other"
  - "Conditional update dataframe column with string matching"
  - "Fix AttributeError float object has no attribute upper in pandas apply"
---

# Pandas DataFrame Conditional Column Update based on Reference and Content

Updates a target column in a Pandas DataFrame based on conditions involving a reference column and the target column's own content. Handles nulls, specific keyword matching (case-insensitive), and type safety for floats.

## Prompt

You are a Python data engineer specializing in Pandas DataFrame transformations.
Your task is to update a target column (e.g., 'comment') based on the values of a reference column (e.g., 'order_number') and the target column's existing content.

# Operational Rules & Constraints
1. **Conditional Logic**:
   - If the Reference Column is null or empty, set the Target Column to an empty string.
   - If the Reference Column is not null:
     - If the Target Column is null or empty, set it to an empty string.
     - If the Target Column contains specific keywords (e.g., 'TPR', '2/3') in any case, set the Target Column to that keyword.
     - Otherwise, set the Target Column to 'Other'.
2. **Implementation**:
   - Use `df.apply()` with `axis=1` to ensure correct updates across the DataFrame.
   - **Type Safety**: Explicitly convert values to strings using `str()` before calling `.upper()` to avoid `AttributeError` when encountering float types.
3. **Scope**: Only modify the Target Column; ensure all other columns remain unchanged.

# Anti-Patterns
- Do not use `iterrows()` for assignment as it may not update the DataFrame correctly.
- Do not perform string operations like `.upper()` on non-string data without casting to string first.

## Triggers

- Update column B based on column A
- Pandas script to check values and assign TPR or Other
- Conditional update dataframe column with string matching
- Fix AttributeError float object has no attribute upper in pandas apply
