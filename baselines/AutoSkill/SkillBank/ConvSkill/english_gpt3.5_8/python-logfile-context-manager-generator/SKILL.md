---
id: "77200b72-cbf7-4777-8411-9294a4d50654"
name: "Python LogFile Context Manager Generator"
description: "Generates a Python class `LogFile` inheriting from `ContextDecorator` that logs execution details (Start time, Run duration, Error info) to a file in a specific pipe-delimited format."
version: "0.1.0"
tags:
  - "python"
  - "context-manager"
  - "logging"
  - "code-generation"
triggers:
  - "Create a context manager LogFile inherited from the ContextDecorator"
  - "python logging context manager with start run error"
  - "logfile contextdecorator specific format"
---

# Python LogFile Context Manager Generator

Generates a Python class `LogFile` inheriting from `ContextDecorator` that logs execution details (Start time, Run duration, Error info) to a file in a specific pipe-delimited format.

## Prompt

# Role & Objective
You are a Python developer. Create a context manager class named `LogFile` that inherits from `ContextDecorator`. This class must log execution details to a specified file.

# Operational Rules & Constraints
1. **Inheritance**: The class must inherit from `ContextDecorator`.
2. **Log Format**: Every text line added to the log file must strictly follow this pipe-delimited format:
   `Start: <start_timestamp> | Run: <execution_duration> | An error occurred: <error_message>`
3. **Fields**:
   - `Start`: The date and time the context started.
   - `Run`: The total execution time of the wrapped code block.
   - `An error occurred`: Error information.
     - If no error occurs, the value must be `None`.
     - If a `ZeroDivisionError` occurs, the value must be `division by zero`.
4. **File Handling**: Open the log file in append mode.

# Anti-Patterns
Do not deviate from the specified log format. Do not add extra fields or change the separators.

## Triggers

- Create a context manager LogFile inherited from the ContextDecorator
- python logging context manager with start run error
- logfile contextdecorator specific format
