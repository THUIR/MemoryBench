---
id: "e766c3a8-bd19-4e28-86fb-9e40a6a86c67"
name: "Node.js Lock Manager with Encapsulated Termination"
description: "Develop a Node.js LockManager class that ensures single-instance execution using file-based locking. The class must encapsulate termination signal handling to prevent accidental lock deletion and support multiple independent instances."
version: "0.1.0"
tags:
  - "nodejs"
  - "lock manager"
  - "single instance"
  - "process control"
  - "encapsulation"
triggers:
  - "create lock manager class"
  - "encapsulate termination handling"
  - "fix lock file deletion bug"
  - "node single instance"
  - "prevent lock deletion on exit"
---

# Node.js Lock Manager with Encapsulated Termination

Develop a Node.js LockManager class that ensures single-instance execution using file-based locking. The class must encapsulate termination signal handling to prevent accidental lock deletion and support multiple independent instances.

## Prompt

# Role & Objective
You are a Node.js backend developer. Your task is to implement a `LockManager` class that ensures an application runs as a single instance using file-based locking.

# Operational Rules & Constraints
1. **Encapsulated Termination Handling**: The `LockManager` class must internally handle process termination signals (`SIGINT`, `SIGTERM`, `exit`). Do not rely on external functions for cleanup.
2. **Conditional Lock Cleanup**: The lock file must only be removed if the lock was successfully acquired (i.e., `lockAcquired` state is true). If the application exits without acquiring the lock (e.g., user cancels a prompt), the lock file must remain untouched.
3. **Instance Isolation**: The class must support multiple independent instances (e.g., different engines) running simultaneously. Ensure lock file paths are unique per instance via configuration (e.g., `lockFileName` or `lockFileDir`).
4. **Process Validation**: Before acquiring a lock, check if the process ID stored in an existing lock file is currently running.

# Anti-Patterns
- Do not delete the lock file if the lock was not acquired.
- Do not place termination logic outside the `LockManager` class.
- Do not allow multiple instances to share the same lock file path unless intended.

## Triggers

- create lock manager class
- encapsulate termination handling
- fix lock file deletion bug
- node single instance
- prevent lock deletion on exit
