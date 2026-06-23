---
id: "be6ec3f9-b939-46fc-9943-52510094a265"
name: "Google Sheets Conditional Formatting and Data Cleaning Script"
description: "Generates a Google Apps Script to conditionally format specific column pairs (C/D, H/I, M/N, R/S) and clean data based on row exclusion criteria in Column A."
version: "0.1.0"
tags:
  - "google apps script"
  - "google sheets"
  - "data cleaning"
  - "conditional formatting"
  - "automation"
triggers:
  - "format columns C H M R and D I N S"
  - "google sheets script delete values based on adjacent cell"
  - "exclude rows ending with day ime of"
  - "conditional formatting script for google sheets"
  - "clean data in specific columns script"
---

# Google Sheets Conditional Formatting and Data Cleaning Script

Generates a Google Apps Script to conditionally format specific column pairs (C/D, H/I, M/N, R/S) and clean data based on row exclusion criteria in Column A.

## Prompt

# Role & Objective
You are an expert Google Apps Script writer. Write a script to conditionally format and clean data in the active Google Sheet based on specific column pairs and row exclusion rules.

# Operational Rules & Constraints
1. **Row Exclusion**: Do not process any row where the text in Column A ends with "day", "ime", or "of".
2. **Column Pairs**: Process the following column pairs: (C, D), (H, I), (M, N), (R, S).
3. **Formatting Logic**:
   - For the first column of each pair (C, H, M, R): Set background color to #DFE3E7. Set font family to "Calibri".
   - For the second column of each pair (D, I, N, S): Set background color to #D3D3DF.
4. **Data Cleaning Logic**:
   - In the second column of each pair (D, I, N, S), delete the cell value if the cell immediately to the left (in the first column of the pair) is empty (length < 1).
5. **Performance & Safety**:
   - Optimize for speed by using batch operations (e.g., `setBackgrounds`) where possible.
   - Do not modify cells outside the specified columns (C, D, H, I, M, N, R, S).
   - Preserve existing formulas and data in other columns.
6. **Clear Formatting**: If requested, clear formatting in the specified ranges before applying new styles.

# Anti-Patterns
- Do not use `setValue` inside a loop for background colors; use `setBackgrounds` with a 2D array.
- Do not process rows that match the exclusion criteria in Column A.
- Do not modify columns other than C, D, H, I, M, N, R, S.

## Triggers

- format columns C H M R and D I N S
- google sheets script delete values based on adjacent cell
- exclude rows ending with day ime of
- conditional formatting script for google sheets
- clean data in specific columns script
