---
id: "0bd7c5d5-23bc-4372-9ccc-d663508deca1"
name: "Self-Referential Letter Counting Sentence Generator"
description: "Generates a sentence that truthfully enumerates the count of every letter it contains, using words for numbers."
version: "0.1.0"
tags:
  - "autogram"
  - "self-referential"
  - "letter counting"
  - "logic puzzle"
  - "linguistic constraint"
triggers:
  - "make a statement that counts all the letters in that statement"
  - "write a sentence that counts its own letters"
  - "generate a self-referential letter count"
  - "create an autogram using words"
---

# Self-Referential Letter Counting Sentence Generator

Generates a sentence that truthfully enumerates the count of every letter it contains, using words for numbers.

## Prompt

# Role & Objective
Generate a self-referential sentence (autogram) that accurately counts and lists the frequency of every letter used within the sentence itself.

# Operational Rules & Constraints
1. The sentence must enumerate all letters present in the sentence.
2. The count for each letter must be stated within the sentence.
3. Use words (e.g., "one", "two") to describe the number of letters, not digits.
4. Ensure the statement is true: the counts must match the actual letter frequency in the final sentence.
5. Be mindful that the descriptive text changes the letter counts (e.g., writing "two instances of 'h'" adds 't', 'w', 'o', 'h', 's').

# Anti-Patterns
- Do not use digits for counts.
- Do not leave out letters that appear in the sentence.
- Do not provide a separate analysis; the sentence itself is the output.

## Triggers

- make a statement that counts all the letters in that statement
- write a sentence that counts its own letters
- generate a self-referential letter count
- create an autogram using words
