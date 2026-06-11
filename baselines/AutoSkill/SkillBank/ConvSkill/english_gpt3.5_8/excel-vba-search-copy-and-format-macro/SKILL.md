---
id: "d1f3522b-2bde-44c8-a460-231ed13b3d38"
name: "Excel VBA Search Copy and Format Macro"
description: "Generates a VBA subroutine to search a source sheet for a user input, copy all matches to a destination sheet, highlight source cells yellow, apply random non-white colors to destination columns, replace destination values with 'X', and log the search term."
version: "0.1.0"
tags:
  - "vba"
  - "excel"
  - "macro"
  - "search"
  - "formatting"
triggers:
  - "create vba macro to search copy and format"
  - "excel vba search highlight yellow random column color"
  - "search and copy data between sheets with formatting"
---

# Excel VBA Search Copy and Format Macro

Generates a VBA subroutine to search a source sheet for a user input, copy all matches to a destination sheet, highlight source cells yellow, apply random non-white colors to destination columns, replace destination values with 'X', and log the search term.

## Prompt

# Role & Objective
You are a VBA expert. Write a subroutine to search a source worksheet for a user-provided value and perform specific copy and formatting operations on a destination worksheet.

# Operational Rules & Constraints
1. **Input**: Prompt the user for a search value via InputBox. Handle empty input by exiting.
2. **Search Logic**: Perform a case-insensitive, partial match search (using `InStr`) across the used range of the Source Sheet. Find ALL occurrences, do not stop at the first.
3. **Copy Operation**: Copy all found cells from the Source Sheet to the Destination Sheet at the exact same cell address.
4. **Source Formatting**: Change the background color of all found cells in the Source Sheet to Yellow (RGB 255, 255, 0).
5. **Destination Value**: Change the value of the copied cells in the Destination Sheet to "X".
6. **Destination Column Formatting**: Identify all columns in the Destination Sheet that received copied data. Apply a random background color to the entire column for each identified column. Ensure the random color generated is NOT white.
7. **Logging**: Copy the search term (the user input) into cell A2 of the Destination Sheet.
8. **Data Structures**: Use a Dictionary object to track unique columns for coloring to avoid errors.

# Anti-Patterns
- Do not stop the search after the first match.
- Do not use `Intersect` on ranges from different sheets or contexts that cause errors; use column tracking instead.
- Do not use `Collection.Exists` (it doesn't exist); use `Scripting.Dictionary`.

## Triggers

- create vba macro to search copy and format
- excel vba search highlight yellow random column color
- search and copy data between sheets with formatting
