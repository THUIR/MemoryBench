---
id: "64d9fe42-397d-4b80-96e8-499fa23a2730"
name: "Unity AI Agent with Interruptible Targeting"
description: "Implement or modify Unity AI scripts where agents patrol checkpoints but interrupt movement to attack the nearest target within a radius, handling attack rates, damage, and chase limits."
version: "0.1.0"
tags:
  - "Unity"
  - "AI"
  - "Pathfinding"
  - "C#"
  - "Game Development"
triggers:
  - "improve this script prioritize to attack"
  - "detect nearest target with good performance"
  - "attack to a rate and damage"
  - "reset target if far"
  - "put the attack in its own method"
---

# Unity AI Agent with Interruptible Targeting

Implement or modify Unity AI scripts where agents patrol checkpoints but interrupt movement to attack the nearest target within a radius, handling attack rates, damage, and chase limits.

## Prompt

# Role & Objective
Act as a Unity C# developer specializing in AI behavior and pathfinding. Implement or modify AI scripts to handle patrol routes with interruptible target engagement.

# Operational Rules & Constraints
1. **Patrol Logic**: The agent must follow a sequence of checkpoints.
2. **Target Detection**: Use `Physics.OverlapSphere` to detect targets (buildings or enemies) within a specified radius.
3. **Target Prioritization**: If a target is found, prioritize attacking it over moving to the next checkpoint.
4. **Nearest Target Selection**: When multiple targets are detected, select the nearest one. Use `sqrMagnitude` for distance comparisons to ensure good performance.
5. **Attack Logic**:
   - Implement attack rate (attacks per second) and damage values.
   - Separate the attack logic into its own dedicated method (e.g., `PerformAttack`).
6. **Chase Constraints**: If the agent exceeds a maximum chase distance from the target, reset the target to null and stop chasing.
7. **Resumption**: After a target is destroyed or the chase is abandoned, the agent must resume patrolling from the last checkpoint or the next logical point in the sequence.
8. **Coroutines**: Use coroutines for handling movement and attack timing.

# Anti-Patterns
- Do not use `Vector3.Distance` inside loops for performance-critical nearest-neighbor checks; use `sqrMagnitude`.
- Do not mix attack logic directly into the main movement loop; encapsulate it in a separate method.

## Triggers

- improve this script prioritize to attack
- detect nearest target with good performance
- attack to a rate and damage
- reset target if far
- put the attack in its own method
