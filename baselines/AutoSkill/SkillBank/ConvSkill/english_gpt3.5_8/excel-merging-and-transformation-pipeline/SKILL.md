---
id: "fd7027a1-d07f-4b9c-88fa-ed25edc4f312"
name: "Excel Merging and Transformation Pipeline"
description: "Merges multiple Excel files selected via GUI, applies specific column transformations (filename extraction, pipe-delimited splitting, arithmetic calculation, renaming), and enriches data using a mapping file."
version: "0.1.0"
tags:
  - "python"
  - "pandas"
  - "excel"
  - "data transformation"
  - "automation"
triggers:
  - "merge excel files with transformations"
  - "process erp data files"
  - "extract project from name column"
  - "join with staff gl mapping"
---

# Excel Merging and Transformation Pipeline

Merges multiple Excel files selected via GUI, applies specific column transformations (filename extraction, pipe-delimited splitting, arithmetic calculation, renaming), and enriches data using a mapping file.

## Prompt

# Role & Objective
Write a Python script using pandas to merge multiple Excel files and perform specific data transformations.

# Operational Rules & Constraints
1. **Input Method**: Use `tkinter.filedialog.askopenfilenames` for input files and `askopenfilename` for the mapping file.
2. **Date Extraction**: Extract the filename without extension from the file path and populate the 'Date' column.
3. **Project Extraction**: Create a 'Project' column by splitting the 'Name' column by "|" and selecting the third value (index 2).
4. **Calculation**: Create a 'Current' column as the difference between 'Debit' and 'Credit'.
5. **Renaming**: Rename 'Closing balance' to 'Cumulative'.
6. **Enrichment**: Perform a left join with the mapping file on 'Main account' to add the 'Name' column.
7. **Output**: Save the result to 'merged_data.xlsx' without index.

## Triggers

- merge excel files with transformations
- process erp data files
- extract project from name column
- join with staff gl mapping
