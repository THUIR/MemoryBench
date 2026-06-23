---
id: "6149bf62-b604-4c05-8d8a-70d2bb6b1d3c"
name: "Extract DataFrame columns by keyword substring list"
description: "Filters a Pandas DataFrame to retain only columns where the column name contains any string from a provided list, using case-insensitive substring matching."
version: "0.1.0"
tags:
  - "pandas"
  - "dataframe"
  - "filtering"
  - "substring"
  - "case-insensitive"
triggers:
  - "extract columns by substring list"
  - "filter columns by keywords case insensitive"
  - "select columns containing list of strings"
  - "get columns with partial name match"
  - "filter dataframe by sustainability list"
---

# Extract DataFrame columns by keyword substring list

Filters a Pandas DataFrame to retain only columns where the column name contains any string from a provided list, using case-insensitive substring matching.

## Prompt

# Role & Objective
Filter DataFrame columns based on a list of keywords using case-insensitive substring matching.

# Operational Rules & Constraints
1. Accept a DataFrame and a list of keyword strings.
2. Iterate through the DataFrame's column names.
3. For each column, check if any keyword from the list is fully contained within the column name.
4. The comparison must be case-insensitive (convert both column name and keyword to lowercase for comparison).
5. Extract and return a new DataFrame containing only the columns that match the criteria.

# Anti-Patterns
- Do not perform exact matching; use substring matching.
- Do not be case-sensitive.

## Triggers

- extract columns by substring list
- filter columns by keywords case insensitive
- select columns containing list of strings
- get columns with partial name match
- filter dataframe by sustainability list
