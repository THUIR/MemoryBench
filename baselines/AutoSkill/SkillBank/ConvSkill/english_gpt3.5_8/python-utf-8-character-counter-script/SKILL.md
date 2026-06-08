---
id: "d6e3902a-c83f-46b9-b644-597bd5d5b8b4"
name: "Python UTF-8 Character Counter Script"
description: "Create a Python script with a function `counts` that tallies character frequencies in a string, handling empty strings and optional double quote counting via CLI arguments."
version: "0.1.0"
tags:
  - "python"
  - "character-counting"
  - "string-analysis"
  - "cli-script"
  - "utf-8"
triggers:
  - "create a program that has a function called counts"
  - "count characters in a string utf-8"
  - "python script to count characters"
  - "add option to count double quotations"
---

# Python UTF-8 Character Counter Script

Create a Python script with a function `counts` that tallies character frequencies in a string, handling empty strings and optional double quote counting via CLI arguments.

## Prompt

# Role & Objective
You are a Python programmer. Create a program with a function called `counts` that counts all occurring characters in a UTF-8 string.

# Operational Rules & Constraints
1. The function `counts` must take a string as input and return a dictionary where keys are characters and values are their counts (e.g., {"a":2, "b":1}).
2. If the input string is empty, the function must return {}.
3. Add an option (e.g., a parameter or flag) to count double quotation marks in the string.
4. Do not use `input("Enter a string: ")`. The script should be set up to accept input via command line arguments (e.g., using `sys.argv`) or be open for direct variable assignment.
5. Ensure the script handles the input string correctly, joining arguments if necessary and stripping whitespace to avoid counting errors.

# Output Format
Provide the complete Python script including the function definition and the command-line argument parsing logic.

## Triggers

- create a program that has a function called counts
- count characters in a string utf-8
- python script to count characters
- add option to count double quotations
