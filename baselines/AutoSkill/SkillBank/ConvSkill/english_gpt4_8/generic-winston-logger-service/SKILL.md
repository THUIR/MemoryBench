---
id: "00a946f0-d1d2-4d6a-a069-5910fcc30478"
name: "Generic Winston Logger Service"
description: "Create a robust, scalable Winston logger service for Node.js projects with daily log rotation, environment-aware formatting, and proper object serialization to prevent [object Object] errors."
version: "0.1.0"
tags:
  - "winston"
  - "logging"
  - "nodejs"
  - "express"
  - "logger"
triggers:
  - "create a generic logger"
  - "winston logger service"
  - "robust logging setup"
  - "fix [object Object] in logs"
  - "scalable logger configuration"
---

# Generic Winston Logger Service

Create a robust, scalable Winston logger service for Node.js projects with daily log rotation, environment-aware formatting, and proper object serialization to prevent [object Object] errors.

## Prompt

# Role & Objective
Create a generic, robust, and scalable Winston logger service for Node.js applications. The logger must be reusable across projects and handle common logging issues like object serialization.

# Operational Rules & Constraints
1. **Dependencies**: Use `winston` and `winston-daily-rotate-file`.
2. **Transports**: Configure both Console and DailyRotateFile transports.
3. **Log Format**:
   - Use `winston.format.metadata()` to capture metadata.
   - Use ISO 8601 timestamps: `YYYY-MM-DDTHH:mm:ssZ`.
   - Implement a custom `printf` function that formats the log string.
4. **Object Serialization**: Ensure that metadata objects and arrays are serialized using `JSON.stringify(metadata, null, 2)` to prevent `[object Object]` output.
5. **Environment Awareness**:
   - Check `process.env.NODE_ENV === 'development'`.
   - Apply `winston.format.colorize()` to the console transport only in development.
6. **Log Rotation**:
   - Rotate logs daily (`datePattern: "YYYY-MM-DD"`).
   - Enable `zippedArchive: true`.
   - Set `maxSize: "20m"` and `maxFiles: "14d"`.
7. **Exception Handling**:
   - Enable `handleExceptions: true` and `exitOnError: false` on transports.
   - Listen for `unhandledRejection` events and log them using the logger.
8. **Parameters**: The function should accept `appName`, `logPath` (defaulting to current working directory), and `logLevel` (defaulting to "info").

# Anti-Patterns
- Do not use deprecated timestamp formats.
- Do not allow `[object Object]` in log output.
- Do not colorize logs in production environments.

## Triggers

- create a generic logger
- winston logger service
- robust logging setup
- fix [object Object] in logs
- scalable logger configuration
