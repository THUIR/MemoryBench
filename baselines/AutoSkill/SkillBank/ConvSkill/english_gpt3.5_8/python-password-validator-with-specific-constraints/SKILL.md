---
id: "ae8a7b1c-62ea-4f68-a62b-c45323eb8bef"
name: "Python Password Validator with Specific Constraints"
description: "Validates a password string against strict rules regarding length, character set diversity, consecutive character limits, and whitespace."
version: "0.1.0"
tags:
  - "python"
  - "password"
  - "validation"
  - "security"
  - "scripting"
triggers:
  - "create a password checker with specific rules"
  - "validate password 14 characters"
  - "python password validation no consecutive chars"
  - "check password against character sets"
---

# Python Password Validator with Specific Constraints

Validates a password string against strict rules regarding length, character set diversity, consecutive character limits, and whitespace.

## Prompt

# Role & Objective
Act as a Python expert programmer. Create a function named `password_checker` that validates a password string against specific, strict rules.

# Operational Rules & Constraints
The function must accept a single string argument (the password) and return a boolean value (True if valid, False otherwise).

The validation logic must enforce the following rules:
1. **Length**: The password must be exactly 14 characters long.
2. **Character Sets**: The password must contain at least one character from each of the following four sets:
   - Uppercase characters (use `string.ascii_uppercase`)
   - Lowercase characters (use `string.ascii_lowercase`)
   - Numerical digits (use `string.digits`)
   - Special characters (use `string.punctuation`)
3. **Consecutive Characters**: The password cannot contain more than three consecutive characters from the same character set.
4. **Whitespace**: The password cannot contain any whitespace characters (use `string.whitespace`).

# Communication & Style Preferences
Provide the Python code implementation clearly. Ensure the `string` module is imported.

## Triggers

- create a password checker with specific rules
- validate password 14 characters
- python password validation no consecutive chars
- check password against character sets
